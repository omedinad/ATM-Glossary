# Glossary files

The app reads SQLite databases produced by `tools/build_glossary.py` (schema 1).
The generic builder uses only Python’s standard library. It validates before
replacing the output; a failed build/import leaves the previous database intact.

## CSV → database

Use UTF-8 comma-separated CSV with this exact header:

```csv
id,abbreviation,meaning,notes,source
example-001,EX,Example term,,Original example by the contributor
```

`id`, `meaning` and `source` are required. IDs must be unique, at most 128 characters,
and contain no whitespace. Keep IDs when correcting terms so favourites and edits
remain attached. Quote fields containing commas, quotes or line breaks using normal
CSV quoting. A UTF-8 BOM is accepted. The limits are 100,000 entries, 100,000 characters
per field and a 64 MiB database. Different meanings may share an acronym.

```sh
python3 tools/build_glossary.py /path/to/terms.csv --strict \
  --metadata /path/to/dataset.json --title "My glossary" \
  --output /path/to/my-glossary.db
```

Optional `--version` supplies a dataset version; otherwise a content hash is used.
`--check` validates without writing. Optional `--aliases aliases.json` accepts a JSON
object mapping retired IDs directly to current IDs after duplicate consolidation.

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

Older databases without a collection ID remain compatible and share the legacy
personal collection. Importing the original database restores access to that
collection’s saved edits/favourites. Add collection metadata to newly created collections.

The bundled CSV automatically uses `data/dataset.json`. Other CSV files use only
metadata explicitly passed with `--metadata`. Do not replace the public CSV with
private content. Keep private inputs and generated import databases outside the repo.

## Bundling a private database

Generate your database with the command above, then build the private edition:

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
python -m pip install -r tools/requirements-import.txt
python tools/import_wikipedia.py /path/to/article.html \
  --retrieved 2026-10-27 --output /tmp/wiki-review/terms.csv
```

Use the actual retrieval date for a new download. Review the output before updating
`data/terms.csv`, `data/dataset.json` and `data/wikipedia-source.json`. If a meaning
changes, retain its existing ID or provide an explicit alias; extraction IDs depend
on acronym/meaning text. Do not claim this collection is official ICAO data or public
domain. Adaptations must retain attribution and CC BY-SA 4.0 terms.
