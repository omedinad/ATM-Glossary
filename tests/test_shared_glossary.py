"""Regression cases for validation parity, safe writes, and legacy compatibility."""
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import entry, write_entries
from tools import build_glossary as builder, export_glossary as exporter
from tools import glossary_core as core, glossary_io as files
from tools import prepare_private_glossary as packaging


class SharedGlossaryTests(unittest.TestCase):
    """Exercise cross-command boundaries using synthetic data and isolated files."""

    def setUp(self):
        """Create a valid CSV and baseline DB whose contents must survive failed operations."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv, self.db = self.root / 'terms.csv', self.root / 'glossary.db'
        write_entries(self.csv, [entry()])
        builder.build(self.csv, self.db)

    def test_source_json_limit_is_checked_before_build(self):
        """Reject individually valid descriptions whose combined JSON exceeds the app limit."""
        metadata = self.root / 'dataset.json'
        metadata.write_text(json.dumps({'collection_id': 'example', 'sources': [
            {'label': 'x' * 6000, 'description': 'y' * 6000} for _ in range(100)]}))
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Source metadata'):
            builder.build(self.csv, self.db, metadata_path=metadata)
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(builder.main([str(self.csv), '--check', '--metadata', str(metadata)]), 1)
        self.assertEqual(self.db.read_bytes(), before)

    def test_normalized_search_length_limit_is_shared(self):
        """Reject valid-length text that expands beyond the stored search-field limit."""
        write_entries(self.csv, [entry(meaning='각' * 40000)])
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'meaning_search'):
            builder.build(self.csv, self.db)
        self.assertEqual(self.db.read_bytes(), before)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE entries SET meaning=?,meaning_search=?', ('각' * 40000, core.normalize('각' * 40000)))
            db.commit()
        with self.assertRaisesRegex(ValueError, 'meaning_search'):
            files.validate_database(self.db)

    def test_utf16_limits_match_android(self):
        """Count non-BMP characters as two units, as Kotlin does, without losing valid text."""
        core.validate_entry(entry(notes='😀' * 50000))
        with self.assertRaisesRegex(ValueError, 'notes'):
            core.validate_entry(entry(notes='😀' * 50001))

    def test_search_and_duplicate_keys_keep_different_accent_rules(self):
        """Keep accent-insensitive search distinct from accent-preserving term identity."""
        self.assertEqual(core.normalize('CAFÉ'), core.normalize('cafe'))
        self.assertNotEqual(core.pair_key(entry(meaning='CAFÉ')), core.pair_key(entry(meaning='cafe')))
        self.assertEqual(core.pair_key(entry(meaning=' A  term ')), core.pair_key(entry(meaning='a term')))

    def test_duplicate_warnings_keep_first_id(self):
        """Every duplicate warning refers to the first matching entry, not a later duplicate."""
        warnings = core.duplicate_warnings([entry(id='first'), entry(id='second'), entry(id='third')])
        self.assertIn('first and second', warnings[0])
        self.assertIn('first and third', warnings[1])

    def test_legacy_and_extensible_source_metadata_remain_importable(self):
        """Permit missing legacy collection IDs and additional source fields in imported DBs."""
        self.assertEqual(files.validate_database(self.db), 1)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('sources', json.dumps([
                {'label': 'Example', 'description': 'Original notes', 'edition': 'Legacy extra field'}])))
            db.commit()
        self.assertEqual(files.validate_database(self.db), 1)
        with self.assertRaisesRegex(ValueError, 'Each source'):
            core.encode_dataset({'collection_id': 'new', 'sources': [
                {'label': 'Example', 'description': 'Notes', 'edition': 'Extra'}]})

    def test_all_commands_use_same_database_rejection(self):
        """Build validation, packaging, and export reject a mismatched entry count alike."""
        contents = files.read_database(self.db)
        bad_metadata = dict(contents.metadata, entry_count='2')
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, 'count'):
            files.write_database(self.db, contents.entries, bad_metadata)
        self.assertEqual(before, self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE metadata SET value='2' WHERE key='entry_count'")
            db.commit()
        for action in (lambda: files.validate_database(self.db),
                       lambda: packaging.prepare(self.db, self.root / 'copy.db'),
                       lambda: exporter.export(self.db, self.root / 'out.csv')):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'count'):
                action()

    def test_failed_replace_preserves_output_and_cleans_temp(self):
        """An OS-level replacement failure must not damage the previous output or leave debris."""
        before = self.db.read_bytes()
        with patch.object(files.os, 'replace', side_effect=OSError('simulated write failure')):
            with self.assertRaisesRegex(OSError, 'simulated'):
                files.write_csv(self.db, [entry()])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['glossary.db', 'terms.csv'])

    def test_json_inputs_cannot_be_overwritten_by_builder(self):
        """Protect metadata/alias inputs as well as the CSV from output-path mistakes."""
        metadata = self.root / 'dataset.json'
        metadata.write_text('{"collection_id":"example"}')
        before = metadata.read_bytes()
        with self.assertRaisesRegex(ValueError, 'must differ'):
            builder.build(self.csv, metadata, metadata_path=metadata)
        self.assertEqual(metadata.read_bytes(), before)

    def test_private_packaging_rejects_uncheckpointed_wal(self):
        """Refuse a live DB whose main file may omit changes while leaving existing output intact."""
        output = self.root / 'copy.db'
        output.write_text('Keep this file')
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute("UPDATE entries SET notes='New note'")
            db.commit()
            with self.assertRaisesRegex(ValueError, 'WAL'):
                packaging.prepare(self.db, output)
        self.assertEqual(output.read_text(), 'Keep this file')

    def test_invalid_metadata_types_report_errors_without_tracebacks(self):
        """Treat malformed SQLite metadata as a validation error at the CLI boundary."""
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE metadata SET value=? WHERE key='title'", (sqlite3.Binary(b'title'),))
            db.commit()
        errors = io.StringIO()
        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
            self.assertEqual(exporter.main([str(self.db), '--check']), 1)
        self.assertIn('ERROR:', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())
