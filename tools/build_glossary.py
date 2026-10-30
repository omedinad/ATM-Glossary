#!/usr/bin/env python3
"""Validate UTF-8 CSV and build an app glossary database using shared validation.

Optional JSON supplies collection metadata and retired-ID aliases. Dataset versions
are content-based unless explicitly supplied; Android version numbers are untouched.
Run python3 tools/build_glossary.py --help for options. No extra packages are needed.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Optional

if __package__:
    from .glossary_core import ROOT, SCHEMA_VERSION
    from .glossary_io import (PathLike, ensure_distinct_paths, read_aliases, read_dataset,
                             read_entries, sidecar_path, write_database)
else:
    from glossary_core import ROOT, SCHEMA_VERSION
    from glossary_io import (PathLike, ensure_distinct_paths, read_aliases, read_dataset,
                            read_entries, sidecar_path, write_database)


def load_inputs(csv_path: PathLike, strict: bool = False,
                alias_path: Optional[PathLike] = None, metadata_path: Optional[PathLike] = None):
    """Load and validate CSV plus its sidecars once for both check-only and build modes."""
    entries, warnings = read_entries(csv_path)
    if strict and warnings:
        raise ValueError('\n'.join(warnings))
    aliases = read_aliases(csv_path, entries, alias_path)
    dataset = read_dataset(csv_path, metadata_path)
    return entries, warnings, aliases, dataset


def build(csv_path: PathLike, output: PathLike, version: Optional[str] = None,
          title: str = 'ATM glossary', strict: bool = False,
          alias_path: Optional[PathLike] = None, metadata_path: Optional[PathLike] = None):
    """Validate inputs and publish a complete DB; return (count, dataset version, warnings).

    The input CSV and optional JSON files are never overwritten. Equivalent pairs
    warn unless strict is enabled. Output is replaced only after full database
    validation. The default version hashes sorted entries, aliases, and metadata;
    changing row order alone does not change it. I/O and validation errors propagate.
    """
    csv_path, output = Path(csv_path).resolve(), Path(output).resolve()
    ensure_distinct_paths(output, csv_path,
                          sidecar_path(csv_path, alias_path, 'entry-aliases.json'),
                          sidecar_path(csv_path, metadata_path, 'dataset.json'))
    entries, warnings, aliases, dataset = load_inputs(csv_path, strict, alias_path, metadata_path)
    entries.sort(key=lambda entry: entry['id'])
    # Keep this serialization stable: existing content versions and IDs must not drift on refactors.
    encoded = json.dumps({'entries': entries, 'aliases': aliases, 'metadata': dataset},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    version = version or digest[:12]
    if not version.strip() or not title.strip():
        raise ValueError('Version and title must not be blank')
    metadata = {'schema_version': str(SCHEMA_VERSION), 'dataset_version': version,
                'title': title, 'content_sha256': digest, 'entry_count': str(len(entries))}
    if aliases:
        metadata['entry_aliases'] = json.dumps(aliases, sort_keys=True)
    metadata.update(dataset)
    write_database(output, entries, metadata)
    return len(entries), version, warnings


def main(argv: Optional[list[str]] = None) -> int:
    """Run validation/build; return 0 on success, 1 on data/I/O errors; argparse uses 2 for syntax."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', type=Path, default=ROOT / 'data/terms.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'app/build/generated/glossaryAssets/glossary.db')
    parser.add_argument('--metadata', type=Path, help='Dataset JSON; automatic only for the bundled CSV')
    parser.add_argument('--aliases', type=Path, help='Retired-ID JSON; automatic only for the bundled CSV')
    parser.add_argument('--version', help='Dataset version; defaults to a content hash')
    parser.add_argument('--title', default='ATM glossary')
    parser.add_argument('--strict', action='store_true', help='Treat duplicate-pair warnings as errors')
    parser.add_argument('--check', action='store_true', help='Validate inputs without writing a database')
    args = parser.parse_args(argv)
    try:
        if args.check:
            entries, warnings, _, _ = load_inputs(args.csv, args.strict, args.aliases, args.metadata)
            print(f'Validated {len(entries)} entries; no database written')
        else:
            count, version, warnings = build(args.csv, args.output, args.version, args.title,
                                             args.strict, args.aliases, args.metadata)
            print(f'Built {count} entries, version {version}: {args.output.resolve()}')
        for warning in warnings:
            print('WARNING: ' + warning, file=sys.stderr)
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
