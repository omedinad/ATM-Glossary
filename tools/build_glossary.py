#!/usr/bin/env python3
"""Validate editable UTF-8 CSV and atomically build the app's SQLite glossary.
Only Python's standard library is required. Importing this module has no side effects.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('id', 'abbreviation', 'meaning', 'notes', 'source')
SCHEMA_VERSION = 1


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.strip())
                   if unicodedata.category(c) != 'Mn').lower()


def pair_key(entry):
    # Identity preserves accents; search normalization intentionally does not.
    return tuple(unicodedata.normalize("NFC", " ".join(entry[k].split())).casefold()
                 for k in ("abbreviation", "meaning"))


def read_entries(path):
    entries, errors, warnings = [], [], []
    ids, pairs = set(), {}
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValueError('Expected CSV header: ' + ','.join(FIELDS))
        for row in reader:
            line = reader.line_num
            if None in row or any(v is None for v in row.values()):
                errors.append(f'Line {line}: wrong column count'); continue
            entry = {k: v.strip() for k, v in row.items()}
            if not any(entry.values()):
                continue
            for key in ('id', 'meaning', 'source'):
                if not entry[key]: errors.append(f'Line {line}: missing {key}')
            if any(len(v) > 100000 for v in entry.values()):
                errors.append(f'Line {line}: fields must be at most 100,000 characters')
            if any('\x00' in v for v in entry.values()):
                errors.append(f'Line {line}: NUL characters are not allowed')
            if len(entry['id']) > 128 or any(c.isspace() for c in entry['id']):
                errors.append(f'Line {line}: id must be at most 128 characters with no whitespace')
            if entry['id'] in ids: errors.append(f"Line {line}: duplicate id {entry['id']}")
            ids.add(entry['id'])
            pair = pair_key(entry)
            if pair in pairs:
                warnings.append(f'Line {line}: duplicate abbreviation/meaning pair (first at line {pairs[pair]})')
            pairs[pair] = line
            entries.append(entry)
    if not entries: errors.append('The glossary must contain at least one entry')
    if len(entries) > 100000: errors.append('The glossary exceeds the 100,000 entry import limit')
    if errors: raise ValueError('\n'.join(errors))
    return entries, warnings


def read_aliases(csv_path, entries, alias_path=None):
    if alias_path is None and Path(csv_path).resolve() == (ROOT/'data/terms.csv').resolve():
        candidate = ROOT/'data/entry-aliases.json'
        if candidate.exists(): alias_path = candidate
    if alias_path is None: return {}
    aliases = json.loads(Path(alias_path).read_text(encoding='utf-8'))
    ids = {e['id'] for e in entries}
    if not isinstance(aliases, dict) or len(aliases) > 100000:
        raise ValueError('Invalid entry aliases')
    for old, target in aliases.items():
        if not isinstance(old, str) or not isinstance(target, str) or not old or len(old) > 128 or any(c.isspace() or c == '\x00' for c in old) or old in ids or target not in ids:
            raise ValueError('Alias must map a retired ID directly to an existing entry ID')
    return aliases


def read_dataset(csv_path, metadata_path=None):
    if metadata_path is None and Path(csv_path).resolve() == (ROOT/'data/terms.csv').resolve():
        candidate = ROOT/'data/dataset.json'
        if candidate.exists(): metadata_path = candidate
    if metadata_path is None: return {}
    data = json.loads(Path(metadata_path).read_text(encoding='utf-8'))
    if not isinstance(data, dict): raise ValueError('Dataset metadata must be an object')
    allowed = {'collection_id', 'sources', 'license', 'license_url'}
    if set(data) - allowed: raise ValueError('Unsupported dataset metadata keys')
    collection = data.get('collection_id', '')
    if not isinstance(collection, str) or not collection or len(collection) > 128 or any(c.isspace() or c == '\x00' for c in collection):
        raise ValueError('collection_id must be a stable, nonblank identifier without whitespace')
    sources = data.get('sources', [])
    if not isinstance(sources, list) or len(sources) > 100: raise ValueError('Invalid sources list')
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'label', 'description'}:
            raise ValueError('Each source needs label and description')
        if not all(isinstance(v, str) and v.strip() and len(v) <= 10000 for v in source.values()):
            raise ValueError('Invalid source description')
    for key in ('license', 'license_url'):
        if key in data and (not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > 10000):
            raise ValueError('Invalid licence metadata')
    return {k: json.dumps(v, ensure_ascii=False, sort_keys=True) if k == 'sources' else v for k,v in data.items()}


def build(csv_path, output, version=None, title='ATM glossary', strict=False, alias_path=None, metadata_path=None):
    csv_path, output = Path(csv_path).resolve(), Path(output).resolve()
    if csv_path == output: raise ValueError('CSV input and database output must differ')
    entries, warnings = read_entries(csv_path)
    if strict and warnings: raise ValueError('\n'.join(warnings))
    aliases = read_aliases(csv_path, entries, alias_path)
    dataset = read_dataset(csv_path, metadata_path)
    # Sort by stable ID so CSV row reordering does not change the content version.
    entries.sort(key=lambda e: e['id'])
    encoded = json.dumps({'entries':entries, 'aliases':aliases, 'metadata':dataset}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    version = version or digest[:12]
    if not version.strip() or not title.strip(): raise ValueError('Version and title must not be blank')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=output.name + '.', suffix='.tmp', dir=output.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temp) as db:
            db.executescript('''
                PRAGMA user_version = 1;
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE entries (
                    id TEXT PRIMARY KEY, abbreviation TEXT NOT NULL, meaning TEXT NOT NULL,
                    notes TEXT NOT NULL, source TEXT NOT NULL,
                    abbreviation_search TEXT NOT NULL, meaning_search TEXT NOT NULL
                );
                CREATE INDEX abbreviation_index ON entries(abbreviation_search);
            ''')
            db.executemany('INSERT INTO entries VALUES (?,?,?,?,?,?,?)', [
                tuple(e[k] for k in FIELDS) + (normalize(e['abbreviation']), normalize(e['meaning']))
                for e in entries])
            metadata = {'schema_version':str(SCHEMA_VERSION), 'dataset_version':version,
                        'title':title, 'content_sha256':digest, 'entry_count':str(len(entries))}
            if aliases: metadata['entry_aliases'] = json.dumps(aliases, sort_keys=True)
            metadata.update(dataset)
            db.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
        # The connection is closed before replace, including on Windows.
        db.close()
        if os.path.getsize(temp) > 64 * 1024 * 1024:
            raise ValueError('Database exceeds the app import limit of 64 MB')
        os.replace(temp, output)
    finally:
        if 'db' in locals(): db.close()
        if os.path.exists(temp): os.unlink(temp)
    return len(entries), version, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', type=Path, default=ROOT/'data/terms.csv')
    parser.add_argument('--output', type=Path, default=ROOT/'app/build/generated/glossaryAssets/glossary.db')
    parser.add_argument('--metadata', type=Path, help='Dataset JSON; automatic only for the bundled CSV')
    parser.add_argument('--aliases', type=Path, help='JSON mapping retired IDs to canonical IDs; automatic for the main CSV')
    parser.add_argument('--version', help='Human-readable dataset version; default is a content hash')
    parser.add_argument('--title', default='ATM glossary')
    parser.add_argument('--strict', action='store_true', help='Treat duplicate-pair warnings as errors')
    parser.add_argument('--check', action='store_true', help='Validate CSV without writing a database')
    args = parser.parse_args(argv)
    try:
        if args.check:
            entries, warnings = read_entries(args.csv)
            read_aliases(args.csv, entries, args.aliases)
            read_dataset(args.csv, args.metadata)
            if args.strict and warnings: raise ValueError('\n'.join(warnings))
            print(f'Validated {len(entries)} entries; no database written')
        else:
            count, version, warnings = build(args.csv, args.output, args.version, args.title, args.strict, args.aliases, args.metadata)
            print(f'Built {count} entries, version {version}: {args.output.resolve()}')
        for warning in warnings: print('WARNING: '+warning, file=sys.stderr)
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
