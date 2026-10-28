"""Shared CSV/JSON/SQLite access and safe output publication for glossary commands.

Validation rules live in glossary_core. File helpers never choose a private input
or change app versions. CSV uses UTF-8 and LF endings; database reads are read-only.
"""
from contextlib import closing, contextmanager
import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Iterable, Iterator, Optional, Union

if __package__:
    from .glossary_core import (Entry, FIELDS, ROOT, SCHEMA_VERSION, MAX_DB_BYTES, MAX_ENTRIES,
                               duplicate_warnings, encode_dataset, normalize, validate_aliases,
                               validate_count, validate_database_metadata, validate_entry)
else:
    from glossary_core import (Entry, FIELDS, ROOT, SCHEMA_VERSION, MAX_DB_BYTES, MAX_ENTRIES,
                              duplicate_warnings, encode_dataset, normalize, validate_aliases,
                              validate_count, validate_database_metadata, validate_entry)

PathLike = Union[str, Path]


@dataclass
class DatabaseContents:
    """Validated entries and unmodified string metadata from one database read."""
    entries: list[Entry]
    metadata: dict[str, str]


def ensure_distinct_paths(output: PathLike, *inputs: Optional[PathLike]) -> None:
    """Reject output that names an input, including symlinks and existing hard links."""
    target = Path(output).resolve()
    for source in inputs:
        if source is None:
            continue
        source = Path(source).resolve()
        if source == target or (source.exists() and target.exists() and os.path.samefile(source, target)):
            raise ValueError('Input and output must differ')


@contextmanager
def atomic_output(output: PathLike) -> Iterator[Path]:
    """Yield a sibling temporary file; replace output only if the caller finishes successfully."""
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=output.name + '.', suffix='.tmp', dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def new_output_directory(output: PathLike) -> Iterator[Path]:
    """Publish a complete staged directory; refuse an existing destination and clean up failures."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output directory must not exist; choose a new review directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output.name + '.', dir=output.parent))
    try:
        yield temporary
        if output.exists():
            raise ValueError('Output directory appeared during extraction; choose a new directory')
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def read_entries(path: PathLike) -> tuple[list[Entry], list[str]]:
    """Validate five-column UTF-8 CSV, returning trimmed entries and duplicate-pair warnings."""
    entries, errors, ids = [], [], set()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValueError('Expected CSV header: ' + ','.join(FIELDS))
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                errors.append(f'Line {reader.line_num}: wrong column count')
                continue
            entry = {key: value.strip() for key, value in row.items()}
            if not any(entry.values()):
                continue
            try:
                validate_entry(entry)
                if entry['id'] in ids:
                    raise ValueError(f"duplicate id {entry['id']}")
            except ValueError as error:
                errors.append(f'Line {reader.line_num}: {error}')
            ids.add(entry['id'])
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                validate_count(len(entries))
    if errors:
        raise ValueError('\n'.join(errors))
    validate_count(len(entries))
    return entries, duplicate_warnings(entries)


def write_csv(output: PathLike, entries: Iterable[Entry]) -> None:
    """Atomically write the five fields as UTF-8 CSV with LF endings, preserving supplied order."""
    with atomic_output(output) as temporary:
        with temporary.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
            writer.writeheader()
            writer.writerows(entries)


def write_json(output: PathLike, data: object) -> None:
    """Atomically write readable UTF-8 JSON with a final newline."""
    with atomic_output(output) as temporary:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sidecar_path(csv_path: PathLike, supplied: Optional[PathLike], name: str) -> Optional[Path]:
    """Resolve an explicit JSON file or a bundled-only default; never guess private metadata paths."""
    if supplied is not None:
        return Path(supplied).resolve()
    candidate = ROOT / 'data' / name
    if Path(csv_path).resolve() == (ROOT / 'data/terms.csv').resolve() and candidate.exists():
        return candidate
    return None


def read_aliases(csv_path: PathLike, entries: list[Entry], alias_path: Optional[PathLike] = None) -> dict[str, str]:
    """Load direct retired-ID mappings, using the optional bundled default only for the starter."""
    path = sidecar_path(csv_path, alias_path, 'entry-aliases.json')
    if path is None:
        return {}
    return validate_aliases(json.loads(path.read_text(encoding='utf-8')), {e['id'] for e in entries})


def read_dataset(csv_path: PathLike, metadata_path: Optional[PathLike] = None) -> dict[str, str]:
    """Load dataset JSON and encode validated values for SQLite and content hashing."""
    path = sidecar_path(csv_path, metadata_path, 'dataset.json')
    return {} if path is None else encode_dataset(json.loads(path.read_text(encoding='utf-8')))


def check_database_size(path: PathLike) -> Path:
    """Return the resolved database path after checking existence and the 64 MiB file limit."""
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Database not found: ' + str(path))
    if not 0 < path.stat().st_size <= MAX_DB_BYTES:
        raise ValueError('Database must be nonempty and at most 64 MiB')
    return path


@contextmanager
def read_only_database(path: PathLike) -> Iterator[sqlite3.Connection]:
    """Open an existing SQLite file read-only and always close the connection."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        yield db


def read_database(path: PathLike, full_check: bool = False) -> DatabaseContents:
    """Validate schema, rows, search fields, and metadata in one read transaction; return all entries."""
    path = check_database_size(path)
    with read_only_database(path) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise ValueError('Unsupported glossary schema; rebuild with build_glossary.py')
        pragma = 'integrity_check' if full_check else 'quick_check'
        if db.execute('PRAGMA ' + pragma).fetchall() != [('ok',)]:
            raise ValueError('The database is damaged')
        for table in ('metadata', 'entries'):
            if db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone() != ('table',):
                raise ValueError('Missing glossary table: ' + table)
        metadata = {}
        for key, value in db.execute('SELECT key,value FROM metadata'):
            if not isinstance(key, str) or not isinstance(value, str) or key in metadata:
                raise ValueError('Metadata must have unique text keys and text values')
            metadata[key] = value
        entries, ids = [], set()
        for row in db.execute('SELECT id,abbreviation,meaning,notes,source,abbreviation_search,meaning_search FROM entries ORDER BY id'):
            entry = dict(zip(FIELDS, row[:len(FIELDS)]))
            validate_entry(entry, tuple(row[len(FIELDS):]))
            if entry['id'] in ids:
                raise ValueError('duplicate id ' + entry['id'])
            ids.add(entry['id'])
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                validate_count(len(entries))
        validate_database_metadata(metadata, ids)
        return DatabaseContents(entries, metadata)


def validate_database(path: PathLike) -> int:
    """Validate a database read-only and return its entry count, without deduplicating it."""
    return len(read_database(path).entries)


@contextmanager
def database_snapshot(path: PathLike) -> Iterator[Path]:
    """Capture committed SQLite/WAL contents in a temporary standalone file, then clean it up."""
    path = check_database_size(path)
    with tempfile.TemporaryDirectory(prefix='glossary-snapshot-') as directory:
        snapshot = Path(directory) / 'snapshot.db'
        with read_only_database(path) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        yield snapshot


def write_database(output: PathLike, entries: list[Entry], metadata: dict[str, str]) -> None:
    """Create a database, validate the completed file, and only then replace its destination."""
    with atomic_output(output) as temporary:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript(f'''
                PRAGMA user_version = {SCHEMA_VERSION};
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE entries (
                    id TEXT PRIMARY KEY, abbreviation TEXT NOT NULL, meaning TEXT NOT NULL,
                    notes TEXT NOT NULL, source TEXT NOT NULL,
                    abbreviation_search TEXT NOT NULL, meaning_search TEXT NOT NULL
                );
                CREATE INDEX abbreviation_index ON entries(abbreviation_search);
            ''')
            with db:
                db.executemany('INSERT INTO entries VALUES (?,?,?,?,?,?,?)', (
                    tuple(e[k] for k in FIELDS) + (normalize(e['abbreviation']), normalize(e['meaning']))
                    for e in entries))
                db.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
        read_database(temporary, full_check=True)
