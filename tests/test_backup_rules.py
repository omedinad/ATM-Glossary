"""Check which Android storage categories are eligible for each backup mode."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'app/src/main'
DOMAINS = ('root', 'file', 'database', 'sharedpref', 'external', 'device_root',
           'device_file', 'device_database', 'device_sharedpref')


def allowed(rules, domain, path, transfer=False):
    """Evaluate include/exclude paths and the legacy device-transfer condition."""
    def matches(rule):
        """Match the domain and either a complete directory or an individual file."""
        target = rule.get('path')
        return rule.get('domain') == domain and (target == '.' or path == target or path.startswith(target + '/'))
    includes = rules.findall('include')
    return (not includes or any(matches(r) and (not r.get('requireFlags') or transfer)
                                for r in includes)) and not any(matches(r) for r in rules.findall('exclude'))


class BackupRulesTest(unittest.TestCase):
    """Protect private data from cloud backup while keeping device transfers coherent."""

    def test_cloud_and_old_android_exclude_every_domain(self):
        """No app storage is selected for cloud backup or Android 6–8 backup."""
        modern = ET.parse(ROOT / 'res/xml/data_extraction_rules.xml').getroot()
        old = ET.parse(ROOT / 'res/xml/backup_rules.xml').getroot()
        legacy = ET.parse(ROOT / 'res/xml-v28/backup_rules.xml').getroot()
        for rules in (modern.find('cloud-backup'), old, legacy):
            for domain in DOMAINS:
                for name in ('glossary.db', 'personal.db', 'glossary.xml', 'anything'):
                    self.assertFalse(allowed(rules, domain, name))

    def test_transfer_keeps_collection_and_rejects_unrelated_storage(self):
        """Both supported formats select databases and only the collection preferences."""
        modern = ET.parse(ROOT / 'res/xml/data_extraction_rules.xml').getroot().find('device-transfer')
        legacy = ET.parse(ROOT / 'res/xml-v28/backup_rules.xml').getroot()
        for rules in (modern, legacy):
            for name in ('glossary.db', 'personal.db', 'personal-collection.db', 'personal-collection.db-wal'):
                self.assertTrue(allowed(rules, 'database', name, transfer=True))
            self.assertTrue(allowed(rules, 'sharedpref', 'glossary.xml', transfer=True))
            self.assertFalse(allowed(rules, 'sharedpref', 'unrelated.xml', transfer=True))
            for domain in ('file', 'external', 'root', 'device_database'):
                self.assertFalse(allowed(rules, domain, 'export.db', transfer=True))

    def test_manifest_enables_both_rule_formats(self):
        """Make the tested policies effective on old and new Android versions."""
        app = ET.parse(ROOT / 'AndroidManifest.xml').getroot().find('application')
        prefix = '{http://schemas.android.com/apk/res/android}'
        self.assertEqual('true', app.get(prefix + 'allowBackup'))
        self.assertEqual('@xml/backup_rules', app.get(prefix + 'fullBackupContent'))
        self.assertEqual('@xml/data_extraction_rules', app.get(prefix + 'dataExtractionRules'))
