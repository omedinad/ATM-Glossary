#!/usr/bin/env python3
"""Validate a glossary database and export editable UTF-8 CSV using shared rules.

Preserves IDs and full per-entry citations. CSV omits collection metadata, aliases,
license summaries, and favourites. Use an app-exported database to include personal
changes. --check validates without a CSV; --strict rejects equivalent term pairs.
"""
import argparse
import csv
from pathlib import Path
import sqlite3
import sys
from typing import Optional

if __package__:
    from .glossary_core import duplicate_warnings
    from .glossary_io import PathLike, database_snapshot, ensure_distinct_paths, read_database, write_csv
else:
    from glossary_core import duplicate_warnings
    from glossary_io import PathLike, database_snapshot, ensure_distinct_paths, read_database, write_csv


def export(database: PathLike, output: Optional[PathLike] = None, strict: bool = False):
    """Export validated entries ordered by ID, returning (count, duplicate warnings).

    Omit output for validation only. A temporary snapshot includes committed WAL
    data and is removed afterward, even in check-only mode. No rows are merged or
    dropped. Validation and writing finish before an existing CSV is replaced.
    The source DB is never edited; paths referring to the same file are rejected.
    """
    if output is not None:
        ensure_distinct_paths(output, database)
    with database_snapshot(database) as snapshot:
        contents = read_database(snapshot)
    warnings = duplicate_warnings(contents.entries)
    if strict and warnings:
        raise ValueError('\n'.join(warnings))
    if output is not None:
        write_csv(output, contents.entries)
    return len(contents.entries), warnings


def main(argv: Optional[list[str]] = None) -> int:
    """Run export/check mode; return 0 on success or 1 on data/I/O errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path, help='App glossary.db or an export from the app')
    parser.add_argument('--output', type=Path, help='Destination CSV (required unless --check)')
    parser.add_argument('--check', action='store_true', help='Validate without writing CSV')
    parser.add_argument('--strict', action='store_true', help='Reject equivalent acronym/meaning pairs')
    args = parser.parse_args(argv)
    if args.check and args.output is not None:
        parser.error('--check cannot be combined with --output')
    if not args.check and args.output is None:
        parser.error('--output is required unless --check is used')
    try:
        count, warnings = export(args.database, args.output, args.strict)
        for warning in warnings:
            print('WARNING: ' + warning, file=sys.stderr)
        if args.check:
            print(f'Validated {count} entries; no CSV written')
        else:
            print(f'Exported {count} entries: {args.output.resolve()}')
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
