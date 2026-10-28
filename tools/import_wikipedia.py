#!/usr/bin/env python3
"""Extract aviation abbreviations from saved Wikipedia HTML into a new review directory.

Install tools/requirements-import.txt for this optional tool. It performs no
network requests. The CSV, dataset.json, and wikipedia-source.json are staged
and published together; the destination directory must not already exist.
"""
import argparse
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

if __package__:
    from .glossary_core import Entry, encode_dataset, pair_key, validate_count, validate_entry
    from .glossary_io import PathLike, new_output_directory, write_csv, write_json
else:
    from glossary_core import Entry, encode_dataset, pair_key, validate_count, validate_entry
    from glossary_io import PathLike, new_output_directory, write_csv, write_json

ARTICLE = 'https://en.wikipedia.org/wiki/List_of_aviation,_avionics,_aerospace_and_aeronautical_abbreviations'
TITLE = 'List of aviation, avionics, aerospace and aeronautical abbreviations'
LICENSE = 'https://creativecommons.org/licenses/by-sa/4.0/'
EXPECTED_TABLES = 27
CHANGES = ('Extracted tables; removed citation markers and acronym disambiguation superscripts; '
           'normalized whitespace; consolidated identical acronym/meaning pairs, preserving notes '
           'and row references. Meanings are retained from Wikipedia, not independently verified.')


def find_revision(soup: BeautifulSoup) -> str:
    """Read a numeric permanent revision for this article, rejecting missing or malformed links."""
    for anchor in soup.select('a[href*="oldid="]'):
        query = parse_qs(urlparse(anchor['href']).query)
        if query.get('title', [''])[0] == ARTICLE.rsplit('/', 1)[1]:
            revision = query.get('oldid', [''])[0]
            if re.fullmatch(r'[0-9]+', revision):
                return revision
    raise ValueError('No valid permanent revision link; refusing unversioned extraction')


def table_rows(soup: BeautifulSoup):
    """Yield each row's location and cells after checking the expected article table layout."""
    tables = soup.select('table.wikitable')
    if len(tables) != EXPECTED_TABLES:
        raise ValueError('Expected the 27 alphabetic/symbol tables; review the source layout')
    for table_no, table in enumerate(tables, 1):
        heading = table.find_previous(['h2', 'h3'])
        section = heading.get_text(' ', strip=True).replace('[edit]', '').strip() if heading else str(table_no)
        records = table.find_all('tr')
        if not records:
            raise ValueError(f'Empty table {table_no}')
        header = [cell.get_text(' ', strip=True) for cell in records[0].find_all(['th', 'td'], recursive=False)]
        if header not in (['Abbreviation', 'Term'], ['Abbreviation', 'Term', 'Notes']):
            raise ValueError(f'Unexpected header: {header}')
        for row_no, row in enumerate(records[1:], 1):
            cells = row.find_all(['td', 'th'], recursive=False)
            if not cells and not row.get_text(strip=True):
                continue
            location = f'section {section}, table {table_no}, row {row_no}'
            if not 2 <= len(cells) <= 3 or any(cell.has_attr('rowspan') or cell.has_attr('colspan') for cell in cells):
                raise ValueError('Unexpected cells in ' + location)
            yield location, cells


def clean_cells(cells):
    """Extract citation markers, then remove display-only markup and normalize cell whitespace."""
    references = sorted({anchor['href'].split('#', 1)[1] for cell in cells
                         for anchor in cell.select('sup.reference a[href*="#"]')})
    for cell in cells:
        for tag in cell.select('sup.reference, .mw-editsection, .noprint, .Template-Fact, .Inline-Template'):
            tag.decompose()
        for br in cell.find_all('br'):
            br.replace_with(' / ')
    # Superscript ordinals distinguish meanings; they are not acronym characters.
    for tag in cells[0].find_all('sup'):
        tag.decompose()
    return [' '.join(cell.get_text('', strip=False).split()) for cell in cells], references


def make_citation(revision: str, location: str, retrieved: str, references: list[str]) -> str:
    """Retain article identity, revision, row location, licence, and original citation markers."""
    permalink = ARTICLE.replace('/wiki/', '/w/index.php?title=') + '&oldid=' + revision
    citation = (f'Wikipedia contributors; {TITLE}; revision {revision}; {location}; retrieved {retrieved}; '
                f'{permalink}; CC BY-SA 4.0: {LICENSE}; adapted to glossary format')
    if references:
        citation += '; article citations: ' + ', '.join(references)
    return citation


def merge_entry(rows: dict, entry: Entry) -> None:
    """Combine equivalent pairs while retaining all citations, distinct notes, and stable derived IDs."""
    key = pair_key(entry)
    if key in rows:
        existing = rows[key]
        existing['source'] += '\n' + entry['source']
        notes = entry['notes']
        if notes and notes not in existing['notes'].split('\n\n'):
            existing['notes'] = '\n\n'.join(filter(None, [existing['notes'], notes]))
    else:
        entry['id'] = 'wiki-aviation-' + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20]
        rows[key] = entry


def extract(html: str, retrieved: str):
    """Return validated, sorted entries and a provenance report; no files are written.

    retrieved must be an ISO YYYY-MM-DD date. Incomplete rows are reported instead
    of guessed; distinct meanings remain separate. Unexpected layouts fail clearly.
    IDs depend on acronym/meaning text, so later wording changes need ID/alias review.
    """
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', retrieved):
        raise ValueError('Retrieval date must use YYYY-MM-DD')
    date.fromisoformat(retrieved)
    soup = BeautifulSoup(html, 'html.parser')
    revision = find_revision(soup)
    rows, skipped, input_count = {}, [], 0
    for location, cells in table_rows(soup):
        input_count += 1
        values, references = clean_cells(cells)
        abbreviation, meaning = values[:2]
        if not abbreviation or not meaning:
            skipped.append({'location': location, 'reason': 'Missing abbreviation or meaning', 'values': values})
            continue
        entry = dict(abbreviation=abbreviation, meaning=meaning,
                     notes=values[2] if len(values) == 3 else '',
                     source=make_citation(revision, location, retrieved, references))
        merge_entry(rows, entry)
    entries = sorted(rows.values(), key=lambda entry: entry['id'])
    validate_count(len(entries))
    for entry in entries:
        validate_entry(entry)
    report = {'article': ARTICLE, 'title': TITLE, 'contributors': ARTICLE + '?action=history',
              'permanent_link': ARTICLE.replace('/wiki/', '/w/index.php?title=') + '&oldid=' + revision,
              'revision': revision, 'retrieved': retrieved,
              'html_sha256': hashlib.sha256(html.encode()).hexdigest(), 'license': 'CC-BY-SA-4.0',
              'license_url': LICENSE, 'input_rows': input_count, 'entries': len(entries),
              'duplicates_consolidated': input_count - len(entries) - len(skipped),
              'skipped': skipped, 'changes': CHANGES}
    return entries, report


def dataset_from_report(report: dict) -> dict:
    """Create collection metadata using the same revision and attribution as the extracted entries."""
    description = (f"Adapted from {TITLE}, by Wikipedia contributors. Revision {report['revision']}, retrieved {report['retrieved']}.\n\n"
                   f"Source: {report['permanent_link']}\nContributors: {report['contributors']}\nLicence: CC BY-SA 4.0 — {LICENSE}\n\n"
                   f"{report['changes']} The article requests additional citations. This starter is an unofficial reference, not a current operational authority.")
    dataset = {'collection_id': 'wikipedia-aviation-starter', 'license': 'CC-BY-SA-4.0', 'license_url': LICENSE,
               'sources': [{'label': 'Wikipedia aviation abbreviations', 'description': description}]}
    encode_dataset(dataset)
    return dataset


def extract_file(html: PathLike, output: PathLike, retrieved: str) -> tuple[int, dict]:
    """Publish a complete CSV/JSON result in a new directory, preserving previous runs on failure."""
    output = Path(output).resolve()
    if output.name in ('dataset.json', 'wikipedia-source.json'):
        raise ValueError('CSV output name must differ from dataset.json and wikipedia-source.json')
    if output.parent.exists():
        raise ValueError('Output directory must not exist; choose a new review directory')
    entries, report = extract(Path(html).read_text(encoding='utf-8'), retrieved)
    dataset = dataset_from_report(report)
    with new_output_directory(output.parent) as staging:
        write_csv(staging / output.name, entries)
        write_json(staging / 'dataset.json', dataset)
        write_json(staging / 'wikipedia-source.json', report)
    return len(entries), report


def main(argv: Optional[list[str]] = None) -> int:
    """Run saved-HTML extraction; return 0 on success or 1 on input/write errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='CSV path in a directory that does not exist yet')
    parser.add_argument('--retrieved', required=True, help='Actual retrieval date, YYYY-MM-DD')
    args = parser.parse_args(argv)
    try:
        count, report = extract_file(args.html, args.output, args.retrieved)
        print(f"Extracted {count} entries from {report['input_rows']} rows; "
              f"{len(report['skipped'])} incomplete rows skipped; {report['duplicates_consolidated']} duplicates combined")
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
