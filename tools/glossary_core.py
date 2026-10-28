"""Shared glossary rules, independent of CSV, SQLite, command lines, and file paths.

Keep these limits compatible with GlossaryRepository.kt. Text lengths use UTF-16
code units, as Android does. Search normalization and duplicate identity are
intentionally separate: duplicate identity preserves accents, search does not.
"""
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('id', 'abbreviation', 'meaning', 'notes', 'source')
SEARCH_FIELDS = ('abbreviation_search', 'meaning_search')
SCHEMA_VERSION = 1
MAX_ENTRIES = 100_000
MAX_FIELD_LENGTH = 100_000
MAX_ID_LENGTH = 128
MAX_DB_BYTES = 64 * 1024 * 1024
MAX_SOURCES = 100
MAX_SOURCE_LENGTH = 10_000
MAX_SOURCES_JSON_LENGTH = 1_100_000
Entry = dict[str, str]


def text_length(value: str) -> int:
    """Count UTF-16 code units so Python enforces Android's String.length limits."""
    return len(value.encode('utf-16-le')) // 2


def normalize(value: str) -> str:
    """Trim, remove accent marks, and lowercase text for the app's search columns."""
    return ''.join(c for c in unicodedata.normalize('NFD', value.strip())
                   if unicodedata.category(c) != 'Mn').lower()


def pair_key(entry: Mapping[str, str]) -> tuple[str, str]:
    """Compare acronym/meaning pairs without case or excess whitespace, keeping accents."""
    return tuple(unicodedata.normalize('NFC', ' '.join(entry[k].split())).casefold()
                 for k in ('abbreviation', 'meaning'))


def validate_text(value: Any, label: str, limit: int = MAX_FIELD_LENGTH,
                  required: bool = False) -> None:
    """Require text within the Android length limit, without NUL or blank required values."""
    if not isinstance(value, str):
        raise ValueError(f'{label} must be text')
    if required and not value.strip():
        raise ValueError(f'missing {label}')
    if '\x00' in value or text_length(value) > limit:
        raise ValueError(f'{label} must contain at most {limit:,} UTF-16 units and no NUL characters')


def validate_identifier(value: Any, label: str = 'id', allow_empty: bool = False) -> None:
    """Check stable IDs; empty collection IDs are allowed only for legacy databases."""
    validate_text(value, label, MAX_ID_LENGTH, required=not allow_empty)
    if any(c.isspace() for c in value):
        raise ValueError(f'{label} must contain no whitespace')


def validate_entry(entry: Mapping[str, Any], search: Optional[tuple[str, str]] = None) -> None:
    """Validate entry fields and normalized search text, optionally checking stored columns."""
    for field in FIELDS:
        validate_text(entry.get(field), field, required=field in ('id', 'meaning', 'source'))
    validate_identifier(entry['id'])
    expected = (normalize(entry['abbreviation']), normalize(entry['meaning']))
    for field, value in zip(SEARCH_FIELDS, expected):
        validate_text(value, field)
    if search is not None:
        for field, value in zip(SEARCH_FIELDS, search):
            validate_text(value, field)
        if search != expected:
            raise ValueError('Invalid search fields; rebuild the database')


def validate_count(count: int) -> None:
    """Keep glossaries nonempty and within the app's entry limit."""
    if not 1 <= count <= MAX_ENTRIES:
        raise ValueError(f'The glossary must contain 1–{MAX_ENTRIES:,} entries')


def duplicate_warnings(entries: Iterable[Mapping[str, str]]) -> list[str]:
    """Report equivalent pairs against the first matching ID, without removing rows."""
    first = {}
    warnings = []
    for entry in entries:
        key = pair_key(entry)
        if key in first:
            warnings.append(f"duplicate abbreviation/meaning pair: {first[key]} and {entry['id']}")
        else:
            first[key] = entry['id']
    return warnings


def validate_aliases(aliases: Any, ids: set[str]) -> dict[str, str]:
    """Require direct mappings from absent retired IDs to existing current IDs."""
    if not isinstance(aliases, dict) or len(aliases) > MAX_ENTRIES:
        raise ValueError('Invalid entry aliases')
    for old, target in aliases.items():
        try:
            validate_identifier(old, 'retired ID')
        except ValueError as error:
            raise ValueError(f'Alias: {error}') from error
        if not isinstance(target, str) or old in ids or target not in ids:
            raise ValueError('Alias must map a retired ID directly to an existing entry ID')
    return aliases


def validate_sources(sources: Any, strict_keys: bool = False) -> None:
    """Validate source descriptions, tolerating extra keys only in imported databases."""
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError('Invalid sources list')
    for source in sources:
        if not isinstance(source, dict) or (strict_keys and set(source) != {'label', 'description'}):
            raise ValueError('Each source needs label and description')
        for field in ('label', 'description'):
            validate_text(source.get(field), f'source {field}', MAX_SOURCE_LENGTH, required=True)


def validate_sources_json(encoded: Any) -> None:
    """Check the stored JSON size before validating its source descriptions."""
    validate_text(encoded, 'Source metadata', MAX_SOURCES_JSON_LENGTH, required=True)
    validate_sources(json.loads(encoded))


def encode_dataset(data: Any) -> dict[str, str]:
    """Validate editable dataset JSON and encode it for SQLite and content hashing."""
    if not isinstance(data, dict):
        raise ValueError('Dataset metadata must be an object')
    if set(data) - {'collection_id', 'sources', 'license', 'license_url'}:
        raise ValueError('Unsupported dataset metadata keys')
    validate_identifier(data.get('collection_id'), 'collection_id')
    validate_sources(data.get('sources', []), strict_keys=True)
    for key in ('license', 'license_url'):
        if key in data:
            validate_text(data[key], key, MAX_SOURCE_LENGTH, required=True)
    encoded = {k: json.dumps(v, ensure_ascii=False, sort_keys=True) if k == 'sources' else v
               for k, v in data.items()}
    if 'sources' in encoded:
        validate_sources_json(encoded['sources'])
    return encoded


def validate_database_metadata(meta: Mapping[str, str], ids: set[str]) -> None:
    """Check database metadata and aliases while preserving legacy collection compatibility."""
    if meta.get('schema_version') != str(SCHEMA_VERSION):
        raise ValueError('Unsupported glossary metadata')
    for field in ('title', 'dataset_version'):
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Missing dataset {field}')
    # Imported legacy databases may omit collection_id and sources entirely.
    validate_identifier(meta.get('collection_id', ''), 'collection_id', allow_empty=True)
    validate_sources_json(meta.get('sources', '[]'))
    validate_count(len(ids))
    if meta.get('entry_count') != str(len(ids)):
        raise ValueError('Entry count does not match metadata')
    validate_aliases(json.loads(meta.get('entry_aliases', '{}')), ids)
