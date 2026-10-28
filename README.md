# ATM Glossary

An offline Android glossary for aviation and air traffic management. Search terms,
save favourites, edit entries, and import or export your own SQLite glossary.
Android 6.0 or later. No account, network permission or analytics.

The starter contains **1,258 entries** adapted from Wikipedia contributors’
[List of aviation, avionics, aerospace and aeronautical abbreviations](https://en.wikipedia.org/w/index.php?title=List_of_aviation,_avionics,_aerospace_and_aeronautical_abbreviations&oldid=1369384513).
It is **CC BY-SA 4.0, not public domain**. It is an unofficial reference; meanings
have not been independently verified for operational use. Attribution and edition
information are available in **About → Sources and editions**.

## Build

Open this folder in Android Studio. Install **JDK 17**, **Android SDK 35** and
**Build Tools 35.0.0**, plus **Python 3.9+**. Set `ANDROID_HOME` or `sdk.dir` in an
untracked `local.properties` file. Then run:

```sh
./gradlew :app:assemblePublicDebug
```

On Windows use `gradlew.bat :app:assemblePublicDebug -PpythonExecutable=python`.
The public build generates its database from `data/terms.csv`; editing that CSV and
building again includes the updates. No private files are required. The first build
downloads Gradle and Maven dependencies. In Android Studio, sync Gradle after changing
build configuration, then select `publicDebug` or `privateDebug` in **Build Variants**.

| Edition | Release target | Bundled glossary |
| --- | --- | --- |
| Public | `./gradlew :app:assemblePublicRelease` | `data/terms.csv` + `data/dataset.json` |
| Private | `./gradlew :app:assemblePrivateRelease` | `../ATM-Glossary-private.db` |

Private builds validate and copy that external database, preserving its citations.
Use `-PprivateGlossary=/absolute/path/glossary.db` to choose another file outside the
repository. Missing or invalid private input fails the private build. Replace
`Release` with `Debug` for an installable development APK. Use the explicit edition
targets: generic `assembleRelease` / `assembleDebug` build **both** editions.

Release APKs go to `app/build/outputs/apk/public/release/` or `private/release/`.
Signed files are named `ATM-Glossary_v1.7.2.apk` and
`ATM-Glossary-Private_v1.7.2.apk`; the version follows `versionName` in `app/build.gradle`.
Set `ATM_KEYSTORE`, `ATM_STORE_PASSWORD`, `ATM_KEY_ALIAS` and `ATM_KEY_PASSWORD` for
release signing, keeping credentials outside Git. Without them, filenames have an
`-unsigned` suffix and the APKs cannot be installed. Debug APKs have a `-debug` suffix.

Both editions retain the same application ID: installing one replaces the other
when signed with the same certificate. The private app label is **ATM Glossary (Private)**.
A differently signed APK requires migration; it cannot update the installed app.

## Your own glossary

Choose **⋮ → Import glossary.db** to use a compatible database (up to 64 MiB).
**Use bundled glossary** selects the database packaged in the installed edition.
Imported databases stay active across app updates, including edition changes.
Personal edits and favourites are kept by glossary collection.
Export includes visible entries and edits, but not favourites or undo history.
See [glossary format and tools](docs/glossaries.md).

## Checks and licences

```sh
python3 -m unittest discover -s tests -v
./gradlew :app:testPublicDebugUnitTest :app:lintPublicDebug
```

With the private database available, also run `:app:testPrivateDebugUnitTest` and
`:app:lintPrivateDebug`. CI checks only the public edition.

Code: [Apache 2.0](LICENSE), with original application credits in [NOTICE](NOTICE).
Starter data: [CC BY-SA 4.0](LICENSES/cc-by-sa-4.0.txt); [source and changes](data/wikipedia-source.json).
Icon: [CC BY 4.0](artwork/ATTRIBUTION.md). These licences have separate scopes.
Only contribute glossary content you have permission to share under CC BY-SA 4.0;
retain source citations and document changes. Private imported data is not part of this repository.
