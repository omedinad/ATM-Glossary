"""Regression checks for database validation and safe CSV export."""

import csv
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools import build_glossary as builder
from tools import export_glossary as exporter
from tests.fixtures import write_entries


class ExportTests(unittest.TestCase):
    """Exercise CSV round trips, validation failures, and SQLite snapshot handling."""
    def setUp(self):
        """Build a temporary glossary with distinct meanings, Unicode, and multiline citations."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'input.csv'
        self.db = self.root / 'input.db'
        self.output = self.root / 'export.csv'
        self.entries = [dict(id='two', abbreviation='ATC', meaning='Another meaning',
                             notes='', source='Second source'),
                        dict(id='one', abbreviation='ATC', meaning='Café, "approach"',
                             notes='First line\nSecond line', source='Source A\nSource B; CC BY-SA 4.0')]
        self.build()

    def build(self):
        """Write the current fixture entries to CSV and rebuild their database."""
        write_entries(self.csv, self.entries)
        builder.build(self.csv, self.db)

    def test_roundtrip_preserves_fields_and_input(self):
        """Check DB-to-CSV-to-DB entry equality and an unchanged input database."""
        before = self.db.read_bytes()
        self.assertEqual(exporter.export(self.db, self.output, strict=True), (2, []))
        with self.output.open(encoding='utf-8', newline='') as stream:
            self.assertEqual(list(csv.DictReader(stream)), sorted(self.entries, key=lambda e: e['id']))
        rebuilt = self.root / 'rebuilt.db'
        builder.build(self.output, rebuilt, strict=True)
        with closing(sqlite3.connect(rebuilt)) as db, closing(sqlite3.connect(self.db)) as original:
            self.assertEqual(db.execute('SELECT * FROM entries ORDER BY id').fetchall(),
                             original.execute('SELECT * FROM entries ORDER BY id').fetchall())
        self.assertEqual(before, self.db.read_bytes())

    def test_invalid_database_preserves_output(self):
        """Reject invalid schemas, metadata, fields, aliases, and corrupt input safely."""
        self.output.write_text('Keep this file')
        for sql in ["PRAGMA user_version=99", "UPDATE metadata SET value='0' WHERE key='entry_count'",
                    "UPDATE entries SET abbreviation_search='wrong'", "UPDATE entries SET source=''",
                    "UPDATE metadata SET value='{\"old\":\"missing\"}' WHERE key='entry_aliases'"]:
            self.build()
            with closing(sqlite3.connect(self.db)) as db:
                db.execute(sql)
                if 'entry_aliases' in sql:
                    db.execute("INSERT INTO metadata VALUES ('entry_aliases','{\"old\":\"missing\"}')")
                db.commit()
            with self.assertRaises((ValueError, sqlite3.Error)):
                exporter.export(self.db, self.output)
            self.assertEqual(self.output.read_text(), 'Keep this file')
        self.db.write_text('Not SQLite')
        with self.assertRaises(sqlite3.Error):
            exporter.export(self.db, self.output)
        self.assertEqual(self.output.read_text(), 'Keep this file')

    def test_duplicate_pairs_warn_or_fail_without_dropping_rows(self):
        """Keep duplicate rows by default and protect output when strict validation fails."""
        self.entries[1].update(abbreviation='atc', meaning='Another meaning')
        self.build()
        count, warnings = exporter.export(self.db, self.output)
        self.assertEqual(count, 2)
        self.assertEqual(len(warnings), 1)
        before = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            exporter.export(self.db, self.output, strict=True)
        self.assertEqual(before, self.output.read_bytes())

    def test_missing_input_collision_and_hardlink(self):
        """Reject missing input and output paths referring to the source database."""
        with self.assertRaisesRegex(ValueError, 'not found'):
            exporter.export(self.root / 'missing.db', self.output)
        with self.assertRaisesRegex(ValueError, 'must differ'):
            exporter.export(self.db, self.db)
        os.link(self.db, self.output)
        with self.assertRaisesRegex(ValueError, 'must differ'):
            exporter.export(self.db, self.output)

    def test_snapshot_includes_committed_wal_changes(self):
        """Include committed SQLite WAL changes in the exported snapshot."""
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute("UPDATE entries SET notes='Committed WAL note' WHERE id='one'")
            db.commit()
            exporter.export(self.db, self.output)
            self.assertIn('Committed WAL note', self.output.read_text())

    def test_cli_check_and_error(self):
        """Check validation-only success and missing-input failure without creating CSV."""
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(exporter.main([str(self.db), '--check', '--strict']), 0)
            self.assertFalse(self.output.exists())
            self.assertEqual(exporter.main([str(self.root / 'missing.db'), '--output', str(self.output)]), 1)
            self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
