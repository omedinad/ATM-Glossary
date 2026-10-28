#!/usr/bin/env python3
"""Validate the public starter, tracked filenames, and placement of glossary assets.

This CI guard checks current tracked paths and working-tree data. It does not scan
Git history or secret contents, or establish the factual accuracy or rights of terms.
Run python3 tools/check_public.py after staging new files; --help describes usage.
"""
import argparse
import csv
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Iterable, Optional

if __package__:
    from .glossary_core import ROOT
    from .glossary_io import read_entries
else:
    from glossary_core import ROOT
    from glossary_io import read_entries

FORBIDDEN_SUFFIXES = {'.db', '.apk', '.aab', '.jks', '.keystore', '.log', '.pdf', '.xlsx', '.zip'}
FORBIDDEN_DIRECTORIES = {'provenance', 'downloads', '.idea', '.gradle', 'build'}


def check_paths(names: Iterable[str]) -> list[str]:
    """Return tracked paths that violate publication policy, retaining private-flavour source files."""
    problems = []
    for name in names:
        path = Path(name)
        if (path.parts[0] == 'private' or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or any(part in FORBIDDEN_DIRECTORIES for part in path.parts)
                or path.name in ('local.properties', 'keystore.properties') or path.name.startswith('.env')):
            problems.append(name)
    return problems


def check_repository(root: Path) -> list[str]:
    """Check Git paths, shared CSV validity, Wikipedia provenance, and stale asset databases."""
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    problems = check_paths(filter(None, names))
    try:
        entries, warnings = read_entries(root / 'data/terms.csv')
        problems.extend(warnings)
        for entry in entries:
            if not entry['id'].startswith('wiki-aviation-') or any(
                    not line.startswith('Wikipedia contributors;') or 'CC BY-SA 4.0' not in line
                    for line in entry['source'].splitlines()):
                problems.append('Unreviewed starter provenance: ' + entry['id'])
    except (ValueError, OSError, csv.Error, UnicodeError) as error:
        problems.append('Invalid starter CSV: ' + str(error))
    if list((root / 'app/src').glob('**/assets/**/*.db')):
        problems.append('Stale database in source-set assets')
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    """Report publication findings, returning 0 on success and 1 on policy or I/O failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        problems = check_repository(ROOT)
        if problems:
            raise ValueError('Public repository check failed:\n' + '\n'.join(problems))
        print('Public file/provenance checks passed. Review new source licences before expanding the starter.')
        return 0
    except (ValueError, OSError, sqlite3.Error, csv.Error, UnicodeError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
