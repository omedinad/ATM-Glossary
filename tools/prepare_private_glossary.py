#!/usr/bin/env python3
"""Validate and copy an external private glossary into generated variant assets.

Gradle calls this for private builds. Build CSV with build_glossary.py first.
The input stays outside the repository; its bytes and citations are preserved.
Supply a standalone DB: live databases with a nonempty WAL are rejected to avoid
copying outdated data. Export from the app, or close/checkpoint SQLite first.
"""
import argparse
import csv
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Optional

if __package__:
    from .glossary_core import ROOT
    from .glossary_io import PathLike, atomic_output, check_database_size, ensure_distinct_paths, validate_database
else:
    from glossary_core import ROOT
    from glossary_io import PathLike, atomic_output, check_database_size, ensure_distinct_paths, validate_database


def prepare(source: PathLike, output: PathLike) -> int:
    """Copy a standalone external DB, validate before replacement, and return its entry count.

    The source and destination must differ, and the source must be outside the
    public repository. A successful copy preserves every byte. A failed copy or
    validation leaves any previous output intact. Source sidecars are not copied.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    if source.is_relative_to(ROOT):
        raise ValueError('Keep the private input database outside the public repository')
    if not source.is_file():
        raise ValueError('Private glossary not found: ' + str(source) +
                         '. Put ATM-Glossary-private.db beside the repository, or set -PprivateGlossary=/path/to/glossary.db')
    check_database_size(source)
    ensure_distinct_paths(output, source)
    wal = Path(str(source) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Private database has a WAL; export or close/checkpoint it before packaging')
    with atomic_output(output) as temporary:
        shutil.copyfile(source, temporary)
        count = validate_database(temporary)
    return count


def main(argv: Optional[list[str]] = None) -> int:
    """Package private data; return 0 on success or 1 on data/I/O errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(f'Prepared {prepare(args.database, args.output)} private entries: {args.output}')
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
