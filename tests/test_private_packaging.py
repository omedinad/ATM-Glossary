import csv
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import build_glossary as builder
import prepare_private_glossary as packaging


class PrivatePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.output = self.root/'source.db', self.root/'assets/glossary.db'
        csv_path = self.root/'source.csv'
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=builder.FIELDS); writer.writeheader()
            writer.writerow(dict(id='example', abbreviation='EX', meaning='Example term', notes='Test note', source='Synthetic fixture'))
        builder.build(csv_path, self.source)

    def test_copy_preserves_every_byte(self):
        before = self.source.read_bytes()
        self.assertEqual(1, packaging.prepare(self.source, self.output))
        self.assertEqual(before, self.output.read_bytes())
        self.assertEqual(before, self.source.read_bytes())

    def test_missing_source_fails_without_replacing_output(self):
        packaging.prepare(self.source, self.output); before = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'privateGlossary'):
            packaging.prepare(self.root/'missing.db', self.output)
        self.assertEqual(before, self.output.read_bytes())

    def test_corrupt_database_does_not_replace_output(self):
        packaging.prepare(self.source, self.output); before = self.output.read_bytes()
        self.source.write_text('Not SQLite')
        with self.assertRaises(sqlite3.Error): packaging.prepare(self.source, self.output)
        self.assertEqual(before, self.output.read_bytes())

    def test_bad_search_fields_rejected(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE entries SET meaning_search='wrong'")
        with self.assertRaisesRegex(ValueError, 'search fields'):
            packaging.prepare(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_bad_count_or_alias_rejected(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='2' WHERE key='entry_count'")
        with self.assertRaisesRegex(ValueError, 'count'): packaging.prepare(self.source, self.output)
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='1' WHERE key='entry_count'")
            db.execute("INSERT INTO metadata VALUES ('entry_aliases', ?)", ('{"old":"missing"}',))
        with self.assertRaisesRegex(ValueError, 'alias'): packaging.prepare(self.source, self.output)

    def test_input_inside_repository_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside the public repository'):
            packaging.prepare(builder.ROOT/'untracked-private.db', self.output)

    def test_invalid_entry_ids_rejected(self):
        for invalid in ('has space', 'x'*129, 'nul\x00id'):
            with sqlite3.connect(self.source) as db:
                db.execute('UPDATE entries SET id=?',(invalid,))
            with self.assertRaises(ValueError): packaging.prepare(self.source,self.output)


if __name__ == '__main__': unittest.main()
