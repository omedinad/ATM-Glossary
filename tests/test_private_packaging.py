"""Regression checks for copying private glossaries into generated build assets."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools import build_glossary as builder
from tools import prepare_private_glossary as packaging
from tools.glossary_core import ROOT
from tests.fixtures import entry, write_entries


class PrivatePackagingTests(unittest.TestCase):
    """Exercise private packaging without using real private glossary data."""
    def setUp(self):
        """Build a standalone synthetic database outside the repository for each test."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.output = self.root/'source.db', self.root/'assets/glossary.db'
        csv_path = self.root/'source.csv'
        write_entries(csv_path, [entry(id='example', abbreviation='EX', meaning='Example term', notes='Test note')])
        builder.build(csv_path, self.source)

    def test_copy_preserves_every_byte(self):
        """Check that packaging leaves the source unchanged and produces an exact copy."""
        before = self.source.read_bytes()
        self.assertEqual(1, packaging.prepare(self.source, self.output))
        self.assertEqual(before, self.output.read_bytes())
        self.assertEqual(before, self.source.read_bytes())

    def test_missing_source_fails_without_replacing_output(self):
        """Keep the previous output when the source path is missing."""
        packaging.prepare(self.source, self.output); before = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'privateGlossary'):
            packaging.prepare(self.root/'missing.db', self.output)
        self.assertEqual(before, self.output.read_bytes())

    def test_corrupt_database_does_not_replace_output(self):
        """Reject damaged input without replacing the previous output."""
        packaging.prepare(self.source, self.output); before = self.output.read_bytes()
        self.source.write_text('Not SQLite')
        with self.assertRaises(sqlite3.Error): packaging.prepare(self.source, self.output)
        self.assertEqual(before, self.output.read_bytes())

    def test_bad_search_fields_rejected(self):
        """Reject search columns that do not match normalized entry text."""
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE entries SET meaning_search='wrong'")
        with self.assertRaisesRegex(ValueError, 'search fields'):
            packaging.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_bad_count_or_alias_rejected(self):
        """Reject inconsistent entry counts and aliases pointing to missing terms."""
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='2' WHERE key='entry_count'")
        with self.assertRaisesRegex(ValueError, 'count'): packaging.prepare(self.source, self.output)
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='1' WHERE key='entry_count'")
            db.execute("INSERT INTO metadata VALUES ('entry_aliases', ?)", ('{"old":"missing"}',))
        with self.assertRaisesRegex(ValueError, '(?i)alias'): packaging.prepare(self.source, self.output)

    def test_input_inside_repository_is_rejected(self):
        """Require private input databases to stay outside the public repository."""
        with self.assertRaisesRegex(ValueError, 'outside the public repository'):
            packaging.prepare(ROOT/'untracked-private.db', self.output)

    def test_invalid_entry_ids_rejected(self):
        """Reject IDs containing whitespace or NUL, or exceeding the length limit."""
        for invalid in ('has space', 'x'*129, 'nul\x00id'):
            with sqlite3.connect(self.source) as db:
                db.execute('UPDATE entries SET id=?',(invalid,))
            with self.assertRaises(ValueError): packaging.prepare(self.source,self.output)


if __name__ == '__main__': unittest.main()
