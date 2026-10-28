#!/usr/bin/env python3
"""Extract the aviation abbreviation tables from a saved Wikipedia HTML page.

Optional maintenance tool: pip install -r tools/requirements-import.txt.
Normal Android/database builds need only Python's standard library.
"""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from build_glossary import FIELDS, pair_key

ARTICLE = 'https://en.wikipedia.org/wiki/List_of_aviation,_avionics,_aerospace_and_aeronautical_abbreviations'
TITLE = 'List of aviation, avionics, aerospace and aeronautical abbreviations'
LICENSE = 'https://creativecommons.org/licenses/by-sa/4.0/'


def extract(html, retrieved):
    soup = BeautifulSoup(html, 'html.parser')
    revisions = [a['href'] for a in soup.select('a[href*="oldid="]') if 'title=List_of_aviation' in a['href']]
    if not revisions: raise ValueError('No permanent revision link; refusing unversioned extraction')
    revision = re.search(r'oldid=(\d+)', revisions[0]).group(1)
    permalink = ARTICLE.replace('/wiki/', '/w/index.php?title=') + '&oldid=' + revision
    rows, skipped, input_count = {}, [], 0
    tables = soup.select('table.wikitable')
    if len(tables) != 27: raise ValueError('Expected the 27 alphabetic/symbol tables; review the source layout')
    for table_no, table in enumerate(tables, 1):
        heading = table.find_previous(['h2', 'h3'])
        section = heading.get_text(' ', strip=True).replace('[edit]', '').strip() if heading else str(table_no)
        records = table.find_all('tr')
        header = [c.get_text(' ', strip=True) for c in records[0].find_all(['th', 'td'], recursive=False)]
        if header not in (['Abbreviation', 'Term'], ['Abbreviation', 'Term', 'Notes']):
            raise ValueError(f'Unexpected header: {header}')
        for row_no, row in enumerate(records[1:], 1):
            cells = row.find_all(['td', 'th'], recursive=False)
            if not cells and not row.get_text(strip=True): continue
            if not 2 <= len(cells) <= 3 or any(c.has_attr('rowspan') or c.has_attr('colspan') for c in cells):
                raise ValueError(f'Unexpected cells in table {table_no}, row {row_no}')
            input_count += 1
            references = sorted({a['href'].split('#', 1)[1] for c in cells for a in c.select('sup.reference a[href*="#"]')})
            for c in cells:
                for tag in c.select('sup.reference, .mw-editsection, .noprint, .Template-Fact, .Inline-Template'):
                    tag.decompose()
                for br in c.find_all('br'): br.replace_with(' / ')
            # Superscript ordinals distinguish multiple expansions; they are not acronym characters.
            for tag in cells[0].find_all('sup'): tag.decompose()
            values = [' '.join(c.get_text('', strip=False).split()) for c in cells]
            abbreviation, meaning = values[:2]
            notes = values[2] if len(values) == 3 else ''
            location = f'section {section}, table {table_no}, row {row_no}'
            if not abbreviation or not meaning:
                skipped.append({'location': location, 'reason': 'Missing abbreviation or meaning', 'values': values})
                continue
            reference = f'Wikipedia contributors; {TITLE}; revision {revision}; {location}; retrieved {retrieved}; {permalink}; CC BY-SA 4.0: {LICENSE}; adapted to glossary format'
            if references: reference += '; article citations: ' + ', '.join(references)
            item = dict(abbreviation=abbreviation, meaning=meaning, notes=notes, source=reference)
            key = pair_key(item)
            if key in rows:
                existing = rows[key]
                existing['source'] += '\n' + reference
                if notes and notes not in existing['notes'].split('\n\n'):
                    existing['notes'] = '\n\n'.join(filter(None, [existing['notes'], notes]))
            else:
                item['id'] = 'wiki-aviation-' + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20]
                rows[key] = item
    if not rows: raise ValueError('No glossary entries extracted')
    report = {'article': ARTICLE, 'title': TITLE, 'contributors': ARTICLE + '?action=history',
              'permanent_link': permalink, 'revision': revision, 'retrieved': retrieved,
              'html_sha256': hashlib.sha256(html.encode()).hexdigest(), 'license': 'CC-BY-SA-4.0',
              'license_url': LICENSE, 'input_rows': input_count, 'entries': len(rows),
              'duplicates_consolidated': input_count - len(rows) - len(skipped), 'skipped': skipped,
              'changes': 'Extracted tables; removed citation markers and acronym disambiguation superscripts; normalized whitespace; consolidated identical acronym/meaning pairs, preserving notes and row references. Meanings are retained from Wikipedia, not independently verified.'}
    return sorted(rows.values(), key=lambda x: x['id']), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--retrieved', required=True, help='Actual retrieval date, YYYY-MM-DD')
    args = parser.parse_args()
    entries, report = extract(args.html.read_text(encoding='utf-8'), args.retrieved)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n'); writer.writeheader(); writer.writerows(entries)
    (args.output.parent/'wikipedia-source.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    description = (f"Adapted from {TITLE}, by Wikipedia contributors. Revision {report['revision']}, retrieved {args.retrieved}.\n\n"
                   f"Source: {report['permanent_link']}\nContributors: {report['contributors']}\nLicence: CC BY-SA 4.0 — {LICENSE}\n\n"
                   f"{report['changes']} The article requests additional citations. This starter is an unofficial reference, not a current operational authority.")
    dataset = {'collection_id': 'wikipedia-aviation-starter', 'license': 'CC-BY-SA-4.0', 'license_url': LICENSE,
               'sources': [{'label': 'Wikipedia aviation abbreviations', 'description': description}]}
    (args.output.parent/'dataset.json').write_text(json.dumps(dataset, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Extracted {len(entries)} entries from {report['input_rows']} rows; {len(report['skipped'])} incomplete rows skipped; {report['duplicates_consolidated']} duplicates combined")


if __name__ == '__main__': main()
