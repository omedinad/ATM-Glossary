#!/usr/bin/env python3
"""Check that tracked files and bundled terms remain suitable for this public repo."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    forbidden = {'.db', '.apk', '.aab', '.jks', '.keystore', '.log', '.pdf', '.xlsx', '.zip'}
    problems = []
    for name in filter(None, names):
        path = Path(name)
        if path.parts[0] == 'private' or path.suffix.lower() in forbidden or any(x in path.parts for x in ('provenance', 'downloads', '.idea', '.gradle', 'build')) or path.name in ('local.properties', 'keystore.properties') or path.name.startswith('.env'):
            problems.append(name)
    for row in csv.DictReader((ROOT/'data/terms.csv').open(encoding='utf-8')):
        if not row['id'].startswith('wiki-aviation-') or any(not line.startswith('Wikipedia contributors;') or 'CC BY-SA 4.0' not in line for line in row['source'].splitlines()):
            problems.append('Unreviewed starter provenance: '+row['id'])
    if list((ROOT/'app/src').glob('**/assets/**/*.db')): problems.append('Stale database in source-set assets')
    if problems: raise SystemExit('Public repository check failed:\n'+'\n'.join(problems))
    print('Public file/provenance checks passed. Review new source licences before expanding the starter.')

if __name__=='__main__':main()
