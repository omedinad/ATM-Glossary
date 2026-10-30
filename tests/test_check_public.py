"""Regression checks for publication policy and required starter provenance."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import entry, write_entries
from tools import check_public


class PublicCheckTests(unittest.TestCase):
    """Check isolated CSV/path inputs without changing the real Git index or starter."""

    def setUp(self):
        """Create a synthetic public starter and stub the tracked filename listing."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.csv = self.root / 'data/terms.csv'
        self.row = entry(id='wiki-aviation-example', source='Wikipedia contributors; fixture; CC BY-SA 4.0')
        write_entries(self.csv, [self.row])
        stub = patch.object(check_public.subprocess, 'check_output', return_value=b'data/terms.csv\0')
        stub.start()
        self.addCleanup(stub.stop)

    def test_valid_public_starter_passes(self):
        """Accept a structurally valid starter with the expected attribution."""
        self.assertEqual(check_public.check_repository(self.root), [])

    def test_blank_citations_and_other_invalid_fields_are_rejected(self):
        """Shared CSV validation rejects empty provenance and malformed entries before policy checks."""
        for changes in ({'source': ''}, {'meaning': ''}, {'id': 'bad id'}):
            with self.subTest(changes=changes):
                write_entries(self.csv, [dict(self.row, **changes)])
                self.assertIn('Invalid starter CSV:', check_public.check_repository(self.root)[0])

    def test_duplicates_and_non_wikipedia_citations_fail(self):
        """Reject equivalent duplicates and citations that lack the starter's required attribution."""
        write_entries(self.csv, [self.row, dict(self.row, id='wiki-aviation-second')])
        self.assertIn('duplicate', check_public.check_repository(self.root)[0])
        write_entries(self.csv, [dict(self.row, source='Private notes')])
        self.assertIn('Unreviewed', check_public.check_repository(self.root)[0])

    def test_path_policy_keeps_private_flavour_sources(self):
        """Distinguish private input material from the public source code for private variants."""
        bad = ['private/terms.csv', 'source.PDF', 'app/build/output.apk', '.env.local', 'keystore.properties']
        good = ['app/src/private/res/values/strings.xml', 'gradle/wrapper/gradle-wrapper.jar', 'tools/glossary_core.py']
        self.assertEqual(check_public.check_paths(bad + good), bad)

    def test_source_asset_database_is_rejected(self):
        """Catch hand-copied DB assets even when they are not tracked."""
        asset = self.root / 'app/src/main/assets/glossary.db'
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b'fixture')
        self.assertIn('Stale database in source-set assets', check_public.check_repository(self.root))

    def test_cli_uses_consistent_exit_codes(self):
        """Return a concise error and status 1 for findings, or status 0 for a clean checkout."""
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with patch.object(check_public, 'check_repository', return_value=['bad path']):
                self.assertEqual(check_public.main([]), 1)
            with patch.object(check_public, 'check_repository', return_value=[]):
                self.assertEqual(check_public.main([]), 0)
