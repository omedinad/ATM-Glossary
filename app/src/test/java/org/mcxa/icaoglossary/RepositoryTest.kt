// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class RepositoryTest {
    private lateinit var context: Context
    private lateinit var repo: GlossaryRepository
    private lateinit var fixture: File
    private lateinit var bundledInfo: GlossaryInfo
    private var sequence = 0

    /** Creates and imports a synthetic glossary with repeated acronyms, accents, and a retired ID. */
    @Before fun setup() {
        context = RuntimeEnvironment.getApplication()
        repo = GlossaryRepository(context)
        repo.initialize()
        bundledInfo = repo.info()
        fixture = File(context.cacheDir, "fixture.db")
        SQLiteDatabase.openOrCreateDatabase(fixture, null).use { db ->
            db.version = 1
            db.execSQL("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execSQL("CREATE TABLE entries (id TEXT PRIMARY KEY, abbreviation TEXT NOT NULL, meaning TEXT NOT NULL, notes TEXT NOT NULL, source TEXT NOT NULL, abbreviation_search TEXT NOT NULL, meaning_search TEXT NOT NULL)")
            val rows = listOf(Triple("term-atc", "ATC", "Air traffic control"), Triple("term-cafe", "CAFE", "Café example"), Triple("term-other", "ATC", "Another test concept")) +
                (1..250).map { Triple("fixture-$it", "ZZ$it", "Generated test entry $it") }
            rows.forEach { (id, acronym, meaning) ->
                db.execSQL("INSERT INTO entries VALUES (?,?,?,?,?,?,?)", arrayOf(id, acronym, meaning, "Test note", "Synthetic fixture; row $id", GlossaryRepository.normalize(acronym), GlossaryRepository.normalize(meaning)))
            }
            mapOf(
                "schema_version" to "1",
                "dataset_version" to "fixture-v1",
                "title" to "Test glossary",
                "entry_count" to rows.size.toString(),
                "collection_id" to "synthetic-test",
                "entry_aliases" to "{\"retired-atc\":\"term-atc\"}",
                "sources" to "[{\"label\":\"Test source\",\"description\":\"Synthetic examples for tests\"}]",
            ).forEach { (k, v) ->
                db.execSQL("INSERT INTO metadata VALUES (?,?)", arrayOf(k, v))
            }
        }
        repo.importDatabase(Uri.fromFile(fixture))
    }
    /** Closes the repository after each test. */
    @After fun cleanup() { repo.close() }
    /** Finds the fixture's air traffic control entry among the distinct ATC meanings. */
    private fun term() = repo.search("ATC", favouritesOnly = false).terms.single { it.id == "term-atc" }
    /** Copies the fixture to a fresh file and applies any requested database changes. */
    private fun copyFixture(action: (SQLiteDatabase) -> Unit = {}): File {
        val file = File(context.cacheDir, "copy-${sequence++}.db")
        fixture.copyTo(file)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use(action)
        return file
    }
    /** Builds a fixture update with a revised ATC meaning and dataset version. */
    private fun updatedDatabase() = copyFixture {
        it.execSQL("UPDATE entries SET meaning='Updated control', meaning_search='updated control' WHERE id='term-atc'")
        it.execSQL("UPDATE metadata SET value='fixture-v2' WHERE key='dataset_version'")
    }
    /** Imports a test database through the same URI-based entry point used by the app. */
    private fun import(file: File) = repo.importDatabase(Uri.fromFile(file))

    /** Checks that About details remain available from cache even when the database file is hidden. */
    @Test fun aboutInfoAndSourcesAreCachedWithoutReadingDatabase() {
        val expected = repo.info()
        assertEquals("Test source", expected.sources.single().label)
        val file = context.getDatabasePath("glossary.db")
        val hidden = File(file.parentFile, "hidden.db")
        assertTrue(file.renameTo(hidden))
        try { repeat(3) { assertSame(expected, repo.info()) } } finally { assertTrue(hidden.renameTo(file)) }
    }
    /** Checks that imports and switching to the bundle refresh the cached count and source metadata. */
    @Test fun countAndSourceMetadataFollowActiveCollection() {
        val count = repo.info().count
        import(copyFixture {
            it.execSQL("DELETE FROM entries WHERE id='term-cafe'")
            it.execSQL("UPDATE metadata SET value=? WHERE key='entry_count'", arrayOf((count-1).toString()))
            it.execSQL("UPDATE metadata SET value='[]' WHERE key='sources'")
        })
        assertEquals(count-1,repo.info().count)
        assertTrue(repo.info().sources.isEmpty())
        repo.useBundled()
        assertEquals(bundledInfo,repo.info())
    }
    /** Checks case/accent matching, distinct meanings, literal query handling, and the result-limit flag. */
    @Test fun searchesAreNormalizedAndKeepDistinctMeanings() {
        assertEquals(2,repo.search("atc",false).terms.size)
        assertEquals("term-cafe",repo.search("cafe",false).terms.single().id)
        assertTrue(repo.search("' OR 1=1 --",false).terms.isEmpty())
        assertTrue(repo.search("",false).more)
    }
    /** Checks that the result limit does not hide favourites outside the first page of all terms. */
    @Test fun favouritesBeyondFirstTwoHundredAreFound() {
        val term = repo.search("ZZ99",false).terms.single()
        repo.toggleFavourite(term)
        assertEquals(term.id,repo.search("",true).terms.single().id)
    }
    /** Checks that a favourite saved under a retired ID resolves to the current term and can be removed. */
    @Test fun retiredFavouriteIdsResolveAndCanBeRemoved() {
        repo.toggleFavourite(term().copy(id="retired-atc"))
        val saved = repo.search("",true).terms.single()
        assertEquals("term-atc",saved.id)
        repo.toggleFavourite(saved)
        assertTrue(repo.search("",true).terms.isEmpty())
    }
    /** Checks that imported updates and favourites persist after reopening the repository. */
    @Test fun importsAndFavouritesSurviveReopening() {
        repo.toggleFavourite(term()); import(updatedDatabase())
        repo.close(); repo=GlossaryRepository(context); repo.initialize()
        assertEquals("fixture-v2",repo.info().version)
        assertEquals("Updated control",repo.search("",true).terms.single().meaning)
        import(fixture)
        assertEquals("Air traffic control",repo.search("",true).terms.single().meaning)
    }
    /** Checks that malformed imports leave the active terms and cached metadata unchanged. */
    @Test fun invalidImportsPreserveDatabaseAndCache() {
        val before=repo.info()
        val invalid = listOf(
            File(context.cacheDir,"bad.db").apply { writeText("not a database") },
            copyFixture { it.version=99 },
            copyFixture { it.execSQL("UPDATE entries SET meaning_search='wrong' WHERE id='term-atc'") },
            copyFixture { it.execSQL("UPDATE metadata SET value='0' WHERE key='entry_count'") },
            copyFixture { it.execSQL("UPDATE metadata SET value='{\"old\":\"missing\"}' WHERE key='entry_aliases'") },
            copyFixture { it.execSQL("UPDATE metadata SET value='bad id' WHERE key='collection_id'") },
            copyFixture { it.execSQL("UPDATE metadata SET value='[{\"label\":3}]' WHERE key='sources'") },
            copyFixture { it.execSQL("UPDATE entries SET id='invalid id' WHERE id='term-cafe'") },
            copyFixture { it.execSQL("UPDATE entries SET notes=? WHERE id='term-cafe'", arrayOf("bad\u0000note")) }
        )
        invalid.forEach { file ->
            assertTrue(file.name,runCatching { import(file) }.isFailure)
            assertEquals(before,repo.info())
            assertEquals("Air traffic control",term().meaning)
        }
    }
    /** Checks that failure to prepare a collection's personal store preserves the active glossary. */
    @Test fun personalStoreFailureDoesNotReplaceActiveGlossary() {
        val before=repo.info()
        val collection="broken-personal-store"
        val digest=java.security.MessageDigest.getInstance("SHA-256").digest(collection.toByteArray())
            .joinToString("") { "%02x".format(it) }
        // A failed/malformed personal-store migration must not install the new base DB.
        SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("personal-$digest.db"),null).use {
            it.execSQL("CREATE TABLE favourites (entry_id TEXT PRIMARY KEY)")
            it.version=2
        }
        val replacement=copyFixture {
            it.execSQL("UPDATE metadata SET value=? WHERE key='collection_id'",arrayOf(collection))
            it.execSQL("UPDATE entries SET meaning='Replacement', meaning_search='replacement' WHERE id='term-atc'")
        }
        assertTrue(runCatching { import(replacement) }.isFailure)
        assertEquals(before,repo.info())
        assertEquals("Air traffic control",term().meaning)
        repo.close();repo=GlossaryRepository(context);repo.initialize()
        assertEquals(before,repo.info())
    }
    /** Checks that personal edits survive reopening and glossary updates while retaining original sources. */
    @Test fun personalEditsPersistAcrossUpdatesAndRetainSources() {
        val original=term();val count=repo.info().count
        repo.toggleFavourite(original)
        repo.saveEdit(original,"MY-ATC","Personal café example","My note","Notebook p. 7")
        var edited=repo.search("cafe",true).terms.single()
        assertTrue(edited.local);assertTrue(edited.source.contains(original.source))
        assertEquals(count,repo.info().count)
        repo.saveEdit(edited,"MY-ATC","Updated personal example","Second note","Notebook p. 8")
        repo.close();repo=GlossaryRepository(context);repo.initialize()
        import(updatedDatabase())
        edited=repo.search("MY-ATC",true).terms.single()
        assertEquals("Updated personal example",edited.meaning)
        assertFalse(edited.source.contains("Notebook p. 7"))
        repo.restoreTerm(original.id)
        assertEquals("Updated control",repo.search("",true).terms.single().meaning)
    }
    /** Checks that switching collections keeps their personal data separate and restores it on return. */
    @Test fun personalEditsAndFavouritesStayWithTheirCollection() {
        repo.toggleFavourite(term())
        repo.saveEdit(term(),"LOCALONLYTEST","Private test meaning","","Notebook")
        repo.saveEdit(null,"LOCALONLYTEST-NEW","Private addition","","")
        repo.useBundled()
        assertTrue(repo.personalChanges().isEmpty())
        assertTrue(repo.search("LOCALONLYTEST",false).terms.isEmpty())
        assertTrue(repo.search("",true).terms.isEmpty())
        val export=File(context.cacheDir,"public-export.db")
        repo.exportDatabase(Uri.fromFile(export))
        SQLiteDatabase.openDatabase(export.path,null,SQLiteDatabase.OPEN_READONLY).use {
            it.rawQuery("SELECT count(*) FROM entries WHERE abbreviation LIKE 'LOCALONLYTEST%'",null).use { c -> c.moveToFirst();assertEquals(0,c.getInt(0)) }
        }
        import(fixture)
        assertEquals(2,repo.personalChanges().size)
        assertEquals("LOCALONLYTEST",repo.search("",true).terms.single().abbreviation)
    }
    /** Checks that every personal add, removal, undo, and reset updates the cached visible-term count. */
    @Test fun addRemoveRestoreAndResetRefreshCount() {
        val count=repo.info().count
        val id=repo.saveEdit(null,"NEWTERM","Added test term","","")
        assertEquals(count+1,repo.info().count)
        repo.removeTerm(repo.search("NEWTERM",false).terms.single())
        assertEquals(count,repo.info().count);assertTrue(repo.personalChanges().single().deleted)
        repo.undoRemoval(id);assertEquals(count+1,repo.info().count)
        repo.restoreTerm(id);assertEquals(count,repo.info().count)
        repo.removeTerm(term());assertEquals(count-1,repo.info().count)
        repo.restoreTerm("term-atc");assertEquals(count,repo.info().count)
    }
    /** Checks that importing ID aliases moves personal edits and favourites to the current term. */
    @Test fun editsAndFavouritesFollowRetiredIds() {
        import(copyFixture {
            it.execSQL("DELETE FROM metadata WHERE key='entry_aliases'")
            it.execSQL("UPDATE entries SET id='retired-atc' WHERE id='term-atc'")
        })
        val old=repo.search("ATC",false).terms.single { it.id=="retired-atc" }
        repo.toggleFavourite(old);repo.saveEdit(old,"ATC","Personal revised example","","")
        import(fixture)
        val current=repo.search("",true).terms.single()
        assertEquals("term-atc",current.id);assertEquals("Personal revised example",current.meaning)
    }
    /** Checks that export and reimport preserve citations, collection identity, additions, edits, and removals. */
    @Test fun exportRoundtripPreservesSourceMetadataAndChanges() {
        val count=repo.info().count
        repo.saveEdit(term(),"ATC","Exported test meaning","Export note","Reference")
        val added=repo.saveEdit(null,"EXPORTTEST","Added test meaning","","")
        repo.removeTerm(repo.search("CAFE",false).terms.single())
        val file=File(context.cacheDir,"export.db");repo.exportDatabase(Uri.fromFile(file))
        repo.personalChanges().forEach { repo.restoreTerm(it.id) }
        import(file)
        assertEquals(count,repo.info().count)
        assertTrue(repo.personalChanges().isEmpty())
        assertEquals("Test source",repo.info().sources.single().label)
        assertEquals("synthetic-test",repo.info().collectionId)
        assertEquals(added,repo.search("EXPORTTEST",false).terms.single().id)
        assertEquals("Exported test meaning",term().meaning)
        assertTrue(repo.search("CAFE",false).terms.isEmpty())
    }
    /** Checks that blank meanings and NUL characters are rejected without changing the original term. */
    @Test fun invalidEditDoesNotReplaceText() {
        assertTrue(runCatching { repo.saveEdit(term(),"ATC"," ","","") }.isFailure)
        assertTrue(runCatching { repo.saveEdit(term(),"ATC","NUL\u0000","","") }.isFailure)
        assertTrue(repo.personalChanges().isEmpty());assertEquals("Air traffic control",term().meaning)
    }
    /** Checks that restoring or editing a removed term cannot bypass the 100,000-term limit. */
    @Test fun restoringHiddenTermsCannotExceedTheExportableLimit() {
        repo.removeTerm(term())
        val full=copyFixture { db ->
            db.execSQL("""WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<99747)
                INSERT INTO entries SELECT 'limit-'||x,'LIMIT'||x,'Limit test','','Synthetic fixture',
                    'limit'||x,'limit test' FROM n""")
            db.execSQL("UPDATE metadata SET value='100000' WHERE key='entry_count'")
        }
        import(full)
        assertEquals(99999,repo.info().count)
        repo.saveEdit(null,"EXTRA","Personal addition","","")
        assertEquals(100000,repo.info().count)
        val hidden=repo.personalChanges().single { it.id=="term-atc" }
        assertTrue(runCatching { repo.undoRemoval(hidden.id) }.isFailure)
        assertTrue(runCatching { repo.restoreTerm(hidden.id) }.isFailure)
        assertTrue(runCatching { repo.saveEdit(hidden,"ATC","Restored","","") }.isFailure)
        assertEquals(100000,repo.info().count)
        assertTrue(repo.personalChanges().single { it.id==hidden.id }.deleted)
    }
    /** Checks that databases without a collection ID keep their legacy favourites and personal edits. */
    @Test fun legacyDatabaseKeepsExistingFavouritesAndEdits() {
        val legacy=copyFixture { it.execSQL("DELETE FROM metadata WHERE key IN ('collection_id','sources')") }
        repo.close()
        context.deleteDatabase("personal.db")
        SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("personal.db"),null).use {
            it.execSQL("CREATE TABLE favourites (entry_id TEXT PRIMARY KEY)")
            it.execSQL("INSERT INTO favourites VALUES ('term-atc')")
            it.version=1
        }
        repo=GlossaryRepository(context);repo.initialize();import(legacy)
        assertEquals("term-atc",repo.search("",true).terms.single().id)
        repo.saveEdit(term(),"LOCALONLYTEST","Legacy edit","","")
        import(fixture);assertTrue(repo.personalChanges().isEmpty())
        import(legacy);assertEquals("Legacy edit",repo.search("",true).terms.single().meaning)
    }
    /** Checks that a bundled glossary update does not replace an imported collection or its edits. */
    @Test fun importedCollectionSurvivesNewBundleHash() {
        repo.saveEdit(term(),"MYTERM","Personal test entry","","")
        context.getSharedPreferences("glossary",Context.MODE_PRIVATE).edit().putString("bundleHash","old-bundle").commit()
        repo.close();repo=GlossaryRepository(context);repo.initialize()
        assertEquals("synthetic-test",repo.info().collectionId)
        assertEquals("Personal test entry",repo.search("MYTERM",false).terms.single().meaning)
    }
    /** Simulates restoring the selected databases and preferences before the first app launch. */
    @Test fun transferredCollectionRetainsImportEditsAndFavourites() {
        repo.toggleFavourite(term())
        repo.saveEdit(term(), "MY-ATC", "Transferred meaning", "Transferred note", "Notebook")
        val expected = repo.info()
        repo.close()
        val prefs = context.getSharedPreferences("glossary", Context.MODE_PRIVATE)
        val imported = prefs.getBoolean("imported", false)
        val hash = prefs.getString("bundleHash", null)
        val snapshot = context.databaseList().associateWith { context.getDatabasePath(it).readBytes() }
        snapshot.keys.forEach { context.deleteDatabase(it) }
        prefs.edit().clear().commit()
        snapshot.forEach { (name, bytes) -> context.getDatabasePath(name).writeBytes(bytes) }
        prefs.edit().putBoolean("imported", imported).putString("bundleHash", hash).commit()
        repo = GlossaryRepository(context)
        repo.initialize()
        assertEquals(expected, repo.info())
        val restored = repo.search("MY-ATC", favouritesOnly = true).terms.single()
        assertEquals("Transferred meaning", restored.meaning)
        assertEquals("Transferred note", restored.notes)
        assertTrue(restored.favourite)
        assertFalse(context.databaseList().any { it.startsWith("import-") || it.startsWith("bundle-") || it.startsWith("previous-") })
    }
}
