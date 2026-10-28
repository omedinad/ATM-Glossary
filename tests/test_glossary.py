import csv
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builder', ROOT/'tools/build_glossary.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SQL = (ROOT/'app/src/main/assets/search.sql').read_text()

class GlossaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name)/'terms.csv'
        self.db = Path(self.temp.name)/'glossary.db'

    def write(self, entries):
        with self.csv.open('w', encoding='utf-8-sig', newline='') as f:
            w=csv.DictWriter(f, fieldnames=builder.FIELDS); w.writeheader(); w.writerows(entries)

    def entry(self, id='one', abbreviation='ATC', meaning='Air traffic control', notes=''):
        return dict(id=id,abbreviation=abbreviation,meaning=meaning,notes=notes,source='Test fixture')

    def search(self, query):
        q=builder.normalize(query)
        escaped=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(SQL,('%'+escaped+'%','%'+escaped+'%',q,escaped+'%',escaped+'%')).fetchall()

    def test_roundtrip_unicode_quotes_commas_newlines(self):
        e=self.entry(meaning='Café, “approach”',notes="Pilot's note\nSecond line")
        self.write([e]); builder.build(self.csv,self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT id,abbreviation,meaning,notes,source FROM entries').fetchone(),tuple(e[k] for k in builder.FIELDS))
        self.assertEqual(len(self.search('CAFE')),1)

    def test_invalid_csv_preserves_previous_database(self):
        self.write([self.entry()]);builder.build(self.csv,self.db);before=self.db.read_bytes()
        self.write([self.entry(),self.entry(meaning='Duplicate ID')])
        with self.assertRaisesRegex(ValueError,'duplicate id'):builder.build(self.csv,self.db)
        self.assertEqual(self.db.read_bytes(),before)

    def test_required_fields_and_empty_input(self):
        for entries in ([],[self.entry(id='')],[self.entry(meaning='')]):
            self.write(entries)
            with self.assertRaises(ValueError):builder.build(self.csv,self.db)
            self.assertFalse(self.db.exists())

    def test_duplicate_pair_warns_and_strict_rejects(self):
        self.write([self.entry(),self.entry(id='two')])
        self.assertEqual(len(builder.build(self.csv,self.db)[2]),1)
        with self.assertRaisesRegex(ValueError,'duplicate abbreviation'):builder.build(self.csv,self.db,strict=True)

    def test_multiple_meanings_and_full_term_without_abbreviation(self):
        self.write([self.entry(),self.entry(id='two',meaning='Another meaning'),self.entry(id='three',abbreviation='',meaning='Airspace term')])
        builder.build(self.csv,self.db)
        self.assertEqual(len(self.search('ATC')),2)
        self.assertEqual(self.search('Airspace')[0][0],'three')

    def test_exact_abbreviation_precedes_prefix_and_meaning(self):
        self.write([self.entry(id='meaning',abbreviation='AAA',meaning='ATC example'),self.entry(id='prefix',abbreviation='ATCS'),self.entry(id='exact'),self.entry(id='substring',abbreviation='ZATC')])
        builder.build(self.csv,self.db)
        self.assertEqual([r[0] for r in self.search(' atc ')],['exact','prefix','meaning','substring'])

    def test_literal_wildcards_and_sql_injection(self):
        values=['100%','a_b',"pilot's",r'a\b','a*b']
        self.write([self.entry(id=str(i),abbreviation=v,meaning='Example') for i,v in enumerate(values)])
        builder.build(self.csv,self.db)
        for i,v in enumerate(values):self.assertEqual([r[0] for r in self.search(v)],[str(i)])
        self.assertEqual(self.search("' OR 1=1 --"),[])

    def test_content_version_changes_only_with_content(self):
        entries=[self.entry(),self.entry(id='two',abbreviation='ABC')]
        self.write(entries);first=builder.build(self.csv,self.db)[1]
        self.write(entries[::-1]);self.assertEqual(builder.build(self.csv,self.db)[1],first)
        entries[0]['meaning']='Updated';self.write(entries)
        self.assertNotEqual(builder.build(self.csv,self.db)[1],first)

    def test_repeated_build_and_search_limit(self):
        self.write([self.entry(id=str(i),abbreviation=f'T{i:03}') for i in range(250)])
        builder.build(self.csv,self.db);builder.build(self.csv,self.db)
        self.assertEqual(len(self.search('')),201)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0],250)

    def test_bad_shape_and_input_output_collision(self):
        self.csv.write_text('id,meaning\n1,example\n')
        with self.assertRaisesRegex(ValueError,'header'):builder.build(self.csv,self.db)
        self.write([self.entry()])
        with self.assertRaisesRegex(ValueError,'must differ'):builder.build(self.csv,self.csv)

    def test_public_starter_has_attribution_and_no_private_rows(self):
        import json
        entries, warnings = builder.read_entries(ROOT/'data/terms.csv')
        report = json.loads((ROOT/'data/wikipedia-source.json').read_text())
        self.assertFalse(warnings)
        self.assertEqual(len(entries), report['entries'])
        self.assertEqual(report['input_rows'], len(entries) + report['duplicates_consolidated'] + len(report['skipped']))
        for entry in entries:
            self.assertTrue(entry['id'].startswith('wiki-aviation-'))
            for citation in entry['source'].splitlines():
                self.assertTrue(citation.startswith('Wikipedia contributors;'))
                self.assertIn('CC BY-SA 4.0', citation)
                self.assertIn('oldid='+report['revision'], citation)
        self.assertGreater(len([e for e in entries if e['abbreviation']=='ACC']), 1)

    def test_metadata_roundtrip_and_version_changes(self):
        import json
        self.write([self.entry()])
        metadata = self.csv.with_name('dataset.json')
        data = {'collection_id':'example', 'sources':[{'label':'Example', 'description':'Original example collection'}]}
        metadata.write_text(json.dumps(data))
        first = builder.build(self.csv, self.db, metadata_path=metadata)[1]
        with closing(sqlite3.connect(self.db)) as db:
            actual = dict(db.execute('SELECT key,value FROM metadata'))
        self.assertEqual(actual['collection_id'], 'example')
        self.assertEqual(json.loads(actual['sources']), data['sources'])
        data['sources'][0]['description'] = 'Changed source notice'
        metadata.write_text(json.dumps(data))
        self.assertNotEqual(first, builder.build(self.csv, self.db, metadata_path=metadata)[1])

    def test_invalid_metadata_preserves_existing_database(self):
        import json
        self.write([self.entry()]); builder.build(self.csv,self.db)
        before = self.db.read_bytes()
        metadata = self.csv.with_name('dataset.json')
        for data in ({'collection_id':'bad id'}, {'collection_id':'bad\x00id'}, {'collection_id':'good','sources':[{'label':'missing description'}]}, {'collection_id':'good','entry_count':100}):
            metadata.write_text(json.dumps(data))
            with self.assertRaises(ValueError): builder.build(self.csv,self.db,metadata_path=metadata)
            self.assertEqual(before,self.db.read_bytes())

    def test_nul_in_alias_is_rejected(self):
        import json
        self.write([self.entry()])
        aliases=self.csv.with_name('aliases.json')
        aliases.write_text(json.dumps({'old\x00id':'one'}))
        with self.assertRaisesRegex(ValueError,'Alias'):
            builder.build(self.csv,self.db,alias_path=aliases)

if __name__=='__main__':unittest.main()
