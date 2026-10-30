"""Small synthetic inputs shared by tests, independent of production file writers."""
import csv
from pathlib import Path

from tools.glossary_core import FIELDS


def entry(**changes) -> dict[str, str]:
    """Return a valid synthetic term, applying fields needed by a particular test."""
    result = dict(id='one', abbreviation='ATC', meaning='Air traffic control', notes='', source='Synthetic fixture')
    result.update(changes)
    return result


def write_entries(path: Path, entries: list[dict[str, str]], bom: bool = False) -> None:
    """Write fixture CSV directly so production parsing/writing can be tested independently."""
    with path.open('w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(entries)
