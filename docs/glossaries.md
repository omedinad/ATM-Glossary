# Python tools and glossary files

The app reads SQLite databases produced by `tools/build_glossary.py` (schema 1).
Run the commands below from the project root with **Python 3.9+**. On systems
where Python 3 is named `python`, substitute that for `python3`. Quote paths that
contain spaces. Only Wikipedia extraction needs an extra package; the other tools
use Python's standard library. They run locally and do not download source data.

| Script | Input → output | When to use it |
| --- | --- | --- |
| [`build_glossary.py`](../tools/build_glossary.py) | CSV and optional JSON → SQLite DB | Build an importable glossary; Gradle also uses it for public builds. |
| [`export_glossary.py`](../tools/export_glossary.py) | SQLite DB → CSV | Recover editable entries or validate a database. |
| [`prepare_private_glossary.py`](../tools/prepare_private_glossary.py) | External SQLite DB → validated byte-for-byte copy | Gradle uses it to package private variants. |
| [`import_wikipedia.py`](../tools/import_wikipedia.py) | Saved article HTML → CSV and two JSON files | Refresh the public starter in a separate review directory. |
| [`check_public.py`](../tools/check_public.py) | Git filenames and public data → pass/fail report | Check the public repository before committing or publishing. |

All five commands support `--help`. They may also be run as modules from the project
root, for example `python3 -m tools.export_glossary --help`. `check_public.py` needs
no other arguments. Commands return status 0 on success, 1 for validation/I/O or
publication failures, and 2 for invalid arguments. Errors and duplicate warnings
go to standard error. Builder/exporter duplicate warnings fail only with `--strict`;
the public repository check always rejects equivalent duplicate starter entries.

Private CSV, JSON, HTML, and databases belong outside the public repository.
Conversion changes a file's format, not its licence or permission to publish it.

## CSV → database

Use UTF-8 comma-separated CSV with this exact header:

```csv
id,abbreviation,meaning,notes,source
example-001,EX,Example term,,Original example by the contributor
```

The header names and order must match exactly. `id`, `meaning` and `source` are
required; `abbreviation` and `notes` may be empty. IDs must be unique, at most 128
characters, and contain no whitespace. NUL characters are rejected in all fields.
Keep IDs when correcting terms so favourites and edits remain attached. Quote
fields containing commas, quotes or line breaks using normal CSV quoting; double
an embedded quotation mark (`""`) inside a quoted field. A UTF-8 BOM is accepted.
The builder trims leading/trailing field whitespace and skips wholly blank rows.
The limits are 1–100,000 entries, 100,000 UTF-16 code units per field, and a 64 MiB
database. Text length uses Android's counting rules: most characters count as one
unit, while characters such as emoji count as two. The same field limit applies
to the generated search text after accent removal and Unicode decomposition;
`--check` detects text that would expand beyond that limit.
Different meanings may share an acronym. Put full citations in `source`, including
edition/page/URL and reuse terms where known; multiple citations may use newlines
inside a quoted field.

```sh
python3 tools/build_glossary.py /path/to/terms.csv --strict \
  --metadata /path/to/dataset.json --title "My glossary" \
  --output /path/to/my-glossary.db
```

| Argument | Meaning/default |
| --- | --- |
| `csv` | Input CSV; defaults to the repository's `data/terms.csv`. |
| `--output PATH` | DB destination; defaults to `app/build/generated/glossaryAssets/glossary.db`. Gradle supplies a separate output directory for each variant. |
| `--metadata PATH` | Dataset JSON; automatically uses `data/dataset.json` only for the bundled CSV. |
| `--aliases PATH` | Retired-ID JSON; automatically uses `data/entry-aliases.json`, if present, only for the bundled CSV. |
| `--title TEXT` | Dataset title; defaults to `ATM glossary`. |
| `--version TEXT` | Dataset version; defaults to 12 characters of a content hash of entries, aliases, and metadata. |
| `--strict` | Treat equivalent acronym/meaning pairs as errors; otherwise warn and retain every row. |
| `--check` | Validate CSV and associated JSON without building a DB. The final database size is checked only during a build. |

Dataset `--version` is separate from Android's `versionName`/`versionCode`; these
scripts never change the application version. Reordering CSV rows does not change
the generated content version. Duplicate comparison ignores case and excess
whitespace, preserves accents, and compares acronym plus meaning. Notes and sources
do not make an otherwise equivalent pair unique; review them before merging.

For a validation-only check:

```sh
python3 tools/build_glossary.py /path/to/terms.csv --check --strict \
  --metadata /path/to/dataset.json --aliases /path/to/aliases.json
```

Omit `--metadata` or `--aliases` when you do not have those files. On a successful
build, an existing destination DB is replaced. Validation and writing happen before
replacement, including validation of the completed SQLite file, so a failed build
leaves the previous destination intact. The CSV and JSON inputs are not modified;
the output must differ from all of them, including symlinks and hard links.

Example metadata:

```json
{
  "collection_id": "my-own-glossary",
  "sources": [{"label": "My notes", "description": "Original notes, edition 1."}]
}
```

Keep `collection_id` constant across updates to the same glossary, and use a different
ID for an unrelated collection. This separates its personal edits and favourites.
Optional `license` and `license_url` describe the dataset’s actual reuse terms.
Source descriptions can include author, edition, URL, licence and changes. Full
per-entry citations remain in `source` and in exports.

Metadata must be a UTF-8 JSON object. When supplied, `collection_id` is required,
nonblank, at most 128 characters, and must contain no whitespace or NUL. `sources`
may contain up to 100 objects, each with exactly `label` and `description`; both
must be nonblank strings of at most 10,000 characters. Optional `license` and
`license_url` follow the same nonblank/10,000-unit rule. All text limits here use
UTF-16 units as described above, and NUL is rejected. The complete encoded `sources`
JSON must fit within 1,100,000 units, even when its individual descriptions fit.
Other dataset keys are rejected. Imported databases remain compatible with older
source objects containing additional keys; new editable JSON uses the documented
`label`/`description` format.

An optional aliases file is a UTF-8 JSON object, for example:

```json
{"retired-example-002": "example-001"}
```

Each key is a retired ID absent from the CSV; its value must name a current CSV ID.
Keys follow the same length/whitespace/NUL rules as IDs. Aliases must point directly
to current IDs, not to other aliases. Keep this mapping after consolidating entries
so the app can associate old favourites and edits with the retained entry.

Older databases without a collection ID remain compatible and share the legacy
personal collection. Importing the original database restores access to that
collection’s saved edits/favourites. Add collection metadata to newly created collections.

The bundled CSV automatically uses `data/dataset.json`. Other CSV files use only
metadata explicitly passed with `--metadata`. Do not replace the public CSV with
private content. Keep private inputs and generated import databases outside the repo.

## Database → CSV

Use Python 3.9+ from the project directory; no extra packages are needed:

```sh
python3 tools/export_glossary.py /path/to/glossary.db --output /path/to/terms.csv
```

The script validates SQLite integrity, schema, metadata/counts, entry fields,
search fields, and retired-ID aliases before replacing the output. It reads a
snapshot of the input and writes UTF-8 CSV with the same five columns shown above,
sorted by ID. IDs, notes, and complete per-entry source citations are retained;
commas, quotes, Unicode, and line breaks are quoted correctly. An invalid input
leaves an existing output CSV untouched. A successful export replaces that CSV.

The input DB argument is required. `--output PATH` is required for export and must
differ from the input, including symbolic links or hard links to the same file.
`--check` and `--output` cannot be combined. Temporary disk space is used for a
consistent snapshot even in check-only mode. For a live SQLite database, committed
WAL changes are included when its sidecar files remain accessible beside it;
copying only the main file while it is open can omit those changes.

To validate without writing a file:

```sh
python3 tools/export_glossary.py /path/to/glossary.db --check --strict
```

Equivalent acronym/meaning pairs produce warnings; `--strict` rejects them.
Distinct meanings for the same acronym are retained. Validation checks the data
format, not whether a definition is factually correct. Limits match the app:
64 MiB, 100,000 entries, and 100,000 UTF-16 units per original or search field.
Exported CSV uses UTF-8 and LF line endings, shared with the Wikipedia importer.

Use **Export glossary** in the app first to include personal additions, edits,
and removals. Copying only its base database omits those personal changes.
The CSV contains entries only: collection metadata, licence summaries, dataset
title/version, retired-ID aliases, and favourites are not CSV columns. Keep your
original `dataset.json` and aliases file and pass them to `build_glossary.py` when
rebuilding, as described above. Per-entry citations remain in the CSV's `source`
column. Keep exports of private glossaries outside this repository.

For a CSV edited after export, rebuild with the same collection metadata and any
retained aliases, then import the resulting DB in the app:

```sh
python3 tools/export_glossary.py /path/to/glossary.db --output /path/to/terms.csv
# Edit terms.csv, retaining existing IDs and citations.
python3 tools/build_glossary.py /path/to/terms.csv --strict \
  --metadata /path/to/dataset.json --aliases /path/to/aliases.json \
  --title "My glossary" --output /path/to/updated-glossary.db
```

JSON files are not recovered by the exporter: use ones you have retained, and omit
those options if absent. In particular, omitting an existing collection ID changes
which personal store the app selects. Preserve the original ID when rebuilding an
existing collection. Search fields are regenerated, and the dataset version is
recomputed unless `--version` is supplied.

## Bundling a private database

Generate your database using `build_glossary.py`, then build the private edition:

```sh
./gradlew :app:assemblePrivateDebug -PprivateGlossary=/path/to/my-glossary.db
```

The default input is `../ATM-Glossary-private.db`, beside the repository folder.
The private build validates and copies an already-generated database; it does not
rebuild an external CSV. After editing private terms, run the Python builder again,
then Gradle. The public target always uses `data/terms.csv` and its metadata.
Each variant has a separate generated asset directory under ignored `app/build/`;
do not copy databases into `app/src/*/assets`. Private APKs contain private data and
should be kept out of public releases. Their source-specific reuse terms still apply.

Normally Gradle handles `prepare_private_glossary.py`. To validate and copy an
external DB manually:

```sh
python3 tools/prepare_private_glossary.py /path/to/my-glossary.db \
  --output /path/to/validated-copy.db
```

Both arguments are required; this tool has no `--check` or `--strict` option.
It checks the same database structure as the exporter but does not check equivalent
definitions. Its input must be outside the repository, and input/output paths must
differ. Validation occurs on a temporary copy before replacement. A successful copy
preserves the source bytes, including metadata and aliases. Supply a standalone DB
from the builder or the app's export action; close/checkpoint other live databases
first, because this copier does not include WAL sidecars. A nonempty `-wal` file
causes packaging to stop with a clear error instead of copying potentially stale
data. Keep the source closed during copying. Use the CSV exporter's `--check` mode
if you only want validation without a permanent output copy.

An imported glossary remains selected after updating either edition. Choose
**Use bundled glossary** to activate the newly packaged database. Changes and
favourites stay attached to their collection; switching does not erase them.

## Wikipedia starter maintenance

The extraction date, pinned article revision, input hash and skipped rows are in
`data/wikipedia-source.json`. The source page warns that more citations are needed.
We normalize whitespace, remove reference markers and superscript acronym sense
numbers, and combine identical acronym/meaning pairs while keeping all citations
and distinct notes. Two rows without meanings are omitted; no expansions are guessed.
The remaining meanings/notes retain Wikipedia wording and may contain errors.

To reproduce the extraction, save the linked revision as HTML outside the repository:

```sh
python3 -m venv .venv
# Activate .venv using your platform’s normal command.
python3 -m pip install -r tools/requirements-import.txt
python3 tools/import_wikipedia.py /path/to/article.html \
  --retrieved 2026-10-27 --output /path/to/wiki-review/terms.csv
```

The positional HTML path, `--retrieved` date, and `--output` CSV path are required.
Use the actual retrieval date in `YYYY-MM-DD` form; the script validates the date
and records it in citations. It expects this article's 27 tables and a numeric permanent revision
link, and fails on an unexpected layout rather than guessing how to extract it.
This is an article-specific importer, not a generic HTML or PDF converter.

A successful run produces three files in the output CSV's directory:

- The requested CSV: consolidated entries with per-row citations and derived IDs.
- `dataset.json`: collection ID, source description, and licence metadata for the builder.
- `wikipedia-source.json`: revision/URL, input hash, counts, skipped rows, and extraction changes.

The output directory **must not already exist**, even if empty; do not create it
before running the command. Choose a new directory name for each extraction.
The CSV cannot be named `dataset.json` or `wikipedia-source.json`. All three files
are prepared in a temporary sibling directory and published together only when
complete. A failed extraction/write leaves previous results untouched and removes
the temporary files. This changes the former overwrite behavior deliberately to
prevent mixed CSV and metadata editions. Validate the candidate before replacing public inputs:

```sh
python3 tools/build_glossary.py /path/to/wiki-review/terms.csv --check --strict \
  --metadata /path/to/wiki-review/dataset.json
```

Use the actual retrieval date for a new download. Review the output before updating
`data/terms.csv`, `data/dataset.json` and `data/wikipedia-source.json`. If a meaning
changes, retain its existing ID or provide an explicit alias; extraction IDs depend
on acronym/meaning text. Do not claim this collection is official ICAO data or public
domain. Adaptations must retain attribution and CC BY-SA 4.0 terms.

## Public repository checks

Run these from the repository root after changing tools or public glossary data:

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_public.py
```

The tests use synthetic fixtures and the public starter; your private database is
not required. Install `tools/requirements-import.txt` in a virtual environment to
run the Wikipedia tests too; if BeautifulSoup is absent, those tests are explicitly
skipped and the standard-library tests still run. CI installs the dependency so
all tests run there.

`check_public.py` needs a Git checkout and the `git` command. It applies the shared
CSV validation first, including required/nonempty citations and normalized-text
limits, then checks equivalent duplicates and Wikipedia-specific attribution.
It also checks tracked filenames for forbidden private/generated files and `app/src/*/assets` for misplaced `.db`
files. It prints a pass message or exits nonzero with findings. It neither modifies
files nor checks Git history, arbitrary secrets in file contents, or the factual
accuracy of terms. New untracked filenames are not checked until added to Git;
rerun it after staging changes and before committing. CI runs it again on pushes
and pull requests.

## Maintaining the Python code

Keep each command focused on its workflow; reusable rules and file operations
belong in the two shared modules:

| Module | Responsibilities |
| --- | --- |
| [`glossary_core.py`](../tools/glossary_core.py) | Schema/field/size constants; search normalization; duplicate identity; entry, source, metadata, and alias validation. No file I/O. |
| [`glossary_io.py`](../tools/glossary_io.py) | CSV/JSON loading and writing; SQLite validation/snapshots; completed DB construction; safe file and directory publication. Calls the core rules. |

Command modules handle arguments and orchestrate these helpers. They expose
`main(argv=None) -> int`, so tests can check command behavior without terminating
the interpreter. Helper functions raise validation or I/O errors; command boundaries
turn those into concise messages. Both direct-script and package execution are
supported; tests use ordinary `from tools ...` imports instead of changing `sys.path`.
Reusable synthetic test data lives in `tests/fixtures.py`.

When changing validation, update shared rules and regression tests rather than
adding another check to a command. Keep Python limits compatible with
`GlossaryRepository.kt`; Android must still validate imported files independently.
Preserve the deliberate differences between search normalization and duplicate
identity, and between new dataset metadata and legacy imported metadata. Keep the
content-hash serialization stable when refactoring so unchanged data retains its
dataset version.

Both Gradle glossary-generation tasks declare the shared modules as inputs in
`app/build.gradle`. If another helper is introduced, add it there so edits invalidate
generated assets. The Wikipedia extraction dependency remains optional for normal
Android builds. Useful checks after a refactor are the full Python suite, a public
CSV → DB → CSV → DB round trip, and both public/private Gradle asset-generation tasks
when the private input is available. No Python command advances the Android version.

## Android backup and device migration

The app permits selective **device-to-device transfer**, not cloud backup. On
supported Android 9+ devices, Android setup may transfer the database directory
(active `glossary.db`, legacy `personal.db`, collection-specific personal databases,
and SQLite sidecars) together with `glossary.xml` preferences. Keeping the imported
flag alongside the active database prevents startup from replacing an imported
collection with the bundled starter. Personal databases for inactive collections
are retained; their original glossary must be reimported to use those changes.

Other preferences, files, external storage, cache, and temporary exports are not
selected. Import, bundled-installation, and rollback staging now use Android's
`noBackupFilesDir`, which Android excludes from backup. Old crash leftovers from
prior versions in the database directory are not filtered by filename. Both public
and private editions use the same policy. Cloud backup stays disabled to avoid
uploading private source material; Android 6–8 excludes all backup domains.

Rules live in `res/xml/backup_rules.xml` (Android 6–8),
`res/xml-v28/backup_rules.xml` (Android 9–11, device-transfer flag required), and
`res/xml/data_extraction_rules.xml` (Android 12+). They are referenced by the
manifest. There is no in-app backup toggle: the device setup flow and transport
support determine availability. Keep the same app ID and signing certificate.
Manual glossary export remains useful, but does not contain favourites or undo
history; these are included in the personal databases during device transfer.

Validation: Python tests check selection/exclusion across both rule formats;
Robolectric simulates restoring databases and collection preferences, then checks
that an import, edit and favourite survive repository initialization. These tests
do not exercise an Android backup transport. Before release, transfer between two
supported test devices using the same signed build: create a favourite and edit,
import a synthetic glossary, transfer during setup, and verify the import stays
active and the edit/favourite remain. Repeat with the bundled collection and
with saved changes in an inactive collection. Check that unrelated files and
cloud backups are excluded. Never rely on transfer as your only copy of data.

Android reference: https://developer.android.com/identity/data/autobackup
