#!/usr/bin/env python3
"""Validate and copy a local private glossary into a variant's generated assets.

The input stays outside the repository; its bytes, metadata and citations are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from build_glossary import ROOT, normalize


def validate(path):
    if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('Private database must be nonempty and at most 64 MiB')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Unsupported glossary schema; rebuild with build_glossary.py')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Private database is damaged')
        for name in ('metadata', 'entries'):
            if db.execute('SELECT type FROM sqlite_master WHERE name=?', (name,)).fetchone() != ('table',):
                raise ValueError('Missing glossary table: ' + name)
        meta = dict(db.execute('SELECT key,value FROM metadata'))
        if meta.get('schema_version') != '1' or not meta.get('title', '').strip() or not meta.get('dataset_version', '').strip():
            raise ValueError('Missing glossary metadata')
        collection = meta.get('collection_id', '')
        if not isinstance(collection, str) or len(collection) > 128 or any(c.isspace() or c == '\x00' for c in collection):
            raise ValueError('Invalid collection ID')
        encoded_sources = meta.get('sources', '[]')
        if len(encoded_sources) > 1100000: raise ValueError('Source metadata is too large')
        sources = json.loads(encoded_sources)
        if not isinstance(sources, list) or len(sources) > 100: raise ValueError('Invalid source metadata')
        for source in sources:
            if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k].strip() and len(source[k]) <= 10000 for k in ('label', 'description')):
                raise ValueError('Invalid source metadata')
        ids = set()
        for row in db.execute('SELECT id,abbreviation,meaning,notes,source,abbreviation_search,meaning_search FROM entries'):
            if not all(isinstance(v, str) and len(v) <= 100000 and '\x00' not in v for v in row):
                raise ValueError('Invalid glossary entry fields')
            if not all(row[i].strip() for i in (0, 2, 4)) or row[0] in ids:
                raise ValueError('Blank required field or duplicate ID')
            if len(row[0]) > 128 or any(c.isspace() for c in row[0]):
                raise ValueError('Invalid entry ID')
            if (normalize(row[1]), normalize(row[2])) != row[5:7]:
                raise ValueError('Invalid search fields; rebuild with build_glossary.py')
            ids.add(row[0])
        if not 1 <= len(ids) <= 100000 or meta.get('entry_count') != str(len(ids)):
            raise ValueError('Invalid glossary entry count')
        aliases = json.loads(meta.get('entry_aliases', '{}'))
        if not isinstance(aliases, dict) or len(aliases) > 100000:
            raise ValueError('Invalid entry aliases')
        for old, target in aliases.items():
            if not isinstance(old, str) or not old or len(old) > 128 or any(c.isspace() or c == '\x00' for c in old) or old in ids or not isinstance(target, str) or target not in ids:
                raise ValueError('Invalid entry alias')
        return len(ids)
    finally:
        db.close()


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source.is_relative_to(ROOT):
        raise ValueError('Keep the private input database outside the public repository')
    if not source.is_file():
        raise ValueError('Private glossary not found: ' + str(source) +
                         '. Put ATM-Glossary-private.db in the repository parent, or set -PprivateGlossary=/path/to/glossary.db')
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Private database exceeds 64 MiB')
    if source == output: raise ValueError('Input and output must differ')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='private-glossary-', suffix='.db', dir=output.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        count = validate(Path(temporary))
        os.replace(temporary, output)
        return count
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(f'Prepared {prepare(args.database, args.output)} private entries: {args.output}')
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'ERROR: {error}\n')


if __name__ == '__main__': main()
