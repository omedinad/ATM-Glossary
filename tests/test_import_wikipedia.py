"""Small saved-HTML fixtures for the optional Wikipedia extractor; no network access."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_glossary as builder, glossary_io as files

try:
    from tools import import_wikipedia as importer
except ModuleNotFoundError as error:
    if error.name != 'bs4':
        raise
    importer = None


def article_html(first_rows: str = '') -> str:
    """Create 27 synthetic tables and a permanent revision link matching the supported layout."""
    link = '<a href="/w/index.php?title=List_of_aviation,_avionics,_aerospace_and_aeronautical_abbreviations&amp;oldid=123">Permanent link</a>'
    tables = []
    for index in range(27):
        rows = first_rows if index == 0 and first_rows else f'<tr><td>T{index}</td><td>Example {index}</td><td></td></tr>'
        tables.append(f'<h2>Section {index}</h2><table class="wikitable"><tr><th>Abbreviation</th><th>Term</th><th>Notes</th></tr>{rows}</table>')
    return link + ''.join(tables)


@unittest.skipIf(importer is None, 'Install tools/requirements-import.txt to test Wikipedia extraction')
class WikipediaTests(unittest.TestCase):
    """Verify citations, layout errors, and publication of a complete extraction directory."""

    def setUp(self):
        """Save an isolated synthetic HTML input and select a new output directory."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = self.root / 'article.html'
        self.html.write_text(article_html(), encoding='utf-8')
        self.output = self.root / 'review/terms.csv'

    def test_duplicates_keep_citations_notes_and_distinct_meanings(self):
        """Merge equivalent rows without losing provenance and report incomplete rows."""
        html = article_html('<tr><td>ATC<sup>1</sup></td><td>Air traffic control<sup class="reference"><a href="#cite1">1</a></sup></td><td>First</td></tr>'
                            '<tr><td>atc</td><td>air traffic control</td><td>Second</td></tr>'
                            '<tr><td>ATC</td><td>Another concept</td><td></td></tr>'
                            '<tr><td>Incomplete</td><td></td><td></td></tr>')
        entries, report = importer.extract(html, '2026-10-27')
        self.assertEqual(report['duplicates_consolidated'], 1)
        self.assertEqual(len(report['skipped']), 1)
        self.assertEqual(report['input_rows'], 30)
        term = next(entry for entry in entries if entry['meaning'] == 'Air traffic control')
        self.assertEqual(term['notes'], 'First\n\nSecond')
        self.assertEqual(len(term['source'].splitlines()), 2)
        self.assertIn('article citations: cite1', term['source'])
        self.assertEqual(len([entry for entry in entries if entry['abbreviation'].upper() == 'ATC']), 2)

    def test_bad_revision_layout_and_date_fail_clearly(self):
        """Reject missing/nonnumeric revisions, changed table structure, and invalid dates."""
        for html, retrieved in [(article_html().replace('oldid=123', 'oldid=bad'), '2026-10-27'),
                                (article_html().replace('wikitable', 'other', 1), '2026-10-27'),
                                (article_html().replace('<th>Term</th>', '<th>Changed</th>', 1), '2026-10-27'),
                                (article_html(), '2026-02-30'), (article_html(), 'yesterday')]:
            with self.subTest(retrieved=retrieved), self.assertRaises(ValueError):
                importer.extract(html, retrieved)

    def test_complete_directory_is_buildable(self):
        """Publish matching CSV/metadata/report files that the shared builder accepts."""
        count, report = importer.extract_file(self.html, self.output, '2026-10-27')
        self.assertEqual(count, 27)
        self.assertEqual({path.name for path in self.output.parent.iterdir()}, {'terms.csv', 'dataset.json', 'wikipedia-source.json'})
        self.assertEqual(json.loads(self.output.with_name('wikipedia-source.json').read_text()), report)
        db = self.root / 'result.db'
        builder.build(self.output, db, metadata_path=self.output.with_name('dataset.json'), strict=True)
        self.assertEqual(files.validate_database(db), 27)

    def test_existing_directory_is_never_overwritten(self):
        """Refuse reuse of a previous review directory and preserve every existing output."""
        importer.extract_file(self.html, self.output, '2026-10-27')
        before = {path.name: path.read_bytes() for path in self.output.parent.iterdir()}
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            importer.extract_file(self.html, self.output, '2026-10-28')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.parent.iterdir()})

    def test_partial_write_is_not_published(self):
        """A JSON write failure removes staging files and leaves no incomplete review directory."""
        with patch.object(importer, 'write_json', side_effect=OSError('simulated disk failure')):
            with self.assertRaisesRegex(OSError, 'simulated'):
                importer.extract_file(self.html, self.output, '2026-10-27')
        self.assertFalse(self.output.parent.exists())
        self.assertEqual([path.name for path in self.root.iterdir()], ['article.html'])

    def test_csv_cannot_replace_its_metadata_file(self):
        """Reject reserved output names before creating any files."""
        with self.assertRaisesRegex(ValueError, 'must differ'):
            importer.extract_file(self.html, self.output.with_name('dataset.json'), '2026-10-27')
        self.assertFalse(self.output.parent.exists())

    def test_cli_reports_failure_without_traceback(self):
        """Return status 1 and a short message when extraction cannot read its input."""
        errors = io.StringIO()
        with redirect_stderr(errors), redirect_stdout(io.StringIO()):
            self.assertEqual(importer.main([str(self.root / 'missing.html'), '--output', str(self.output), '--retrieved', '2026-10-27']), 1)
        self.assertIn('ERROR:', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())
