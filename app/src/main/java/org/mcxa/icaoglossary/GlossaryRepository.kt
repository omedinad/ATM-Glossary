// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import androidx.core.content.edit
import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.net.Uri
import java.io.File
import java.security.MessageDigest
import java.text.Normalizer
import java.util.Locale

data class Term(val id: String, val abbreviation: String, val meaning: String,
                val notes: String, val source: String, val favourite: Boolean = false,
                val local: Boolean = false, val citation: String = "", val deleted: Boolean = false)
data class GlossaryInfo(val title: String, val version: String, val count: Int,
                        val sources: List<SourceCatalog.Source> = emptyList(), val collectionId: String = "")
data class SearchResult(val terms: List<Term>, val more: Boolean)

// All activity instances use DatabaseWorker, including initialization and close().
class GlossaryRepository(private val context: Context) : AutoCloseable {
    private var cachedInfo: GlossaryInfo? = null
    private var cachedAliases: Map<String, String> = emptyMap()
    private data class ValidatedGlossary(val info: GlossaryInfo, val aliases: Map<String, String>, val ids: Set<String>)
    private val destination = context.getDatabasePath("glossary.db")
    private val prefs = context.getSharedPreferences("glossary", Context.MODE_PRIVATE)
    private var personalName = "personal.db"
    private var personal = createPersonal(personalName)
    private fun createPersonal(name: String) = object : SQLiteOpenHelper(context, name, null, 2) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL("CREATE TABLE favourites (entry_id TEXT PRIMARY KEY)")
            createEdits(db)
        }
        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            if (oldVersion < 2) createEdits(db)
        }
        private fun createEdits(db: SQLiteDatabase) {
            db.execSQL("""CREATE TABLE edits (
                id TEXT PRIMARY KEY, abbreviation TEXT NOT NULL, meaning TEXT NOT NULL,
                notes TEXT NOT NULL, source TEXT NOT NULL,
                abbreviation_search TEXT NOT NULL, meaning_search TEXT NOT NULL,
                origin_source TEXT NOT NULL, citation TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
            )""")
        }
    }
    private val searchSql by lazy { context.assets.open("search.sql").bufferedReader().use { it.readText() } }

    fun initialize() {
        destination.parentFile?.mkdirs()
        val bundledHash = context.assets.open("glossary.db").use { input ->
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(8192)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        }
        val imported = prefs.getBoolean("imported", false)
        if (!destination.exists() || (!imported && prefs.getString("bundleHash", "") != bundledHash)) {
            installBundle(bundledHash)
        } else if (cachedInfo == null) {
            publish(validate(destination))
        }
    }

    private fun open(file: File = destination): SQLiteDatabase =
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY)

    private fun validate(file: File): ValidatedGlossary = open(file).use { db ->
        require(db.version == 1) { "Unsupported glossary schema; use build_glossary.py." }
        db.rawQuery("PRAGMA quick_check", null).use { c ->
            require(c.moveToFirst() && c.getString(0) == "ok") { "The database is damaged." }
        }
        for (table in listOf("metadata", "entries")) {
            db.rawQuery("SELECT type FROM sqlite_master WHERE name=?", arrayOf(table)).use { c ->
                require(c.moveToFirst() && c.getString(0) == "table") { "Missing glossary table: $table" }
            }
        }
        val meta = mutableMapOf<String, String>()
        db.rawQuery("SELECT key,value FROM metadata", null).use { c ->
            while (c.moveToNext()) meta[c.getString(0)] = c.getString(1)
        }
        require(meta["schema_version"] == "1") { "Unsupported glossary metadata." }
        require(!meta["title"].isNullOrBlank() && !meta["dataset_version"].isNullOrBlank()) { "Missing dataset title or version." }
        val collectionId = meta["collection_id"].orEmpty()
        require(collectionId.length <= 128 && collectionId.none { it.isWhitespace() || it == '\u0000' }) { "Invalid collection ID." }
        val sources = mutableListOf<SourceCatalog.Source>()
        meta["sources"]?.let { encoded ->
            require(encoded.length <= 1100000) { "Source metadata is too large." }
            val json = org.json.JSONArray(encoded)
            require(json.length() <= 100) { "Too many sources." }
            for (i in 0 until json.length()) {
                val entry = json.getJSONObject(i)
                val label = entry.get("label")
                val description = entry.get("description")
                require(label is String && label.isNotBlank() && label.length <= 10000 &&
                    description is String && description.isNotBlank() && description.length <= 10000) { "Invalid source metadata." }
                sources.add(SourceCatalog.Source(label as String, description as String))
            }
        }
        db.rawQuery("SELECT id,abbreviation,meaning,notes,source,abbreviation_search,meaning_search FROM entries", null).use { c ->
            require(c.count in 1..100000) { "Glossary must contain 1–100,000 entries." }
            require(meta["entry_count"] == c.count.toString()) { "Entry count does not match metadata." }
            val ids = hashSetOf<String>()
            while (c.moveToNext()) {
                for (i in 0..6) require(!c.isNull(i) && c.getString(i).length <= 100000 && '\u0000' !in c.getString(i)) { "Invalid entry fields." }
                require(c.getString(0).isNotBlank() && c.getString(2).isNotBlank() && c.getString(4).isNotBlank()) { "Missing entry ID, meaning or source." }
                require(c.getString(0).length <= 128 && c.getString(0).none { it.isWhitespace() }) { "Invalid entry ID." }
                require(ids.add(c.getString(0))) { "Duplicate entry ID." }
                require(c.getString(5) == normalize(c.getString(1)) && c.getString(6) == normalize(c.getString(2))) { "Invalid search fields; rebuild the database." }
            }
            val aliases = mutableMapOf<String, String>()
            meta["entry_aliases"]?.let { encoded ->
                val json = org.json.JSONObject(encoded)
                require(json.length() <= 100000) { "Too many entry aliases." }
                json.keys().forEach { old ->
                    val target = json.get(old)
                    require(target is String && old.isNotBlank() && old.length <= 128 &&
                        old.none { it.isWhitespace() || it == '\u0000' } && old !in ids && target in ids) { "Invalid entry alias." }
                    aliases[old] = target as String
                }
            }
            ValidatedGlossary(GlossaryInfo(meta.getValue("title"), meta.getValue("dataset_version"), c.count, sources, collectionId), aliases, ids)
        }
    }

    private fun publish(validated: ValidatedGlossary, replacement: File? = null) {
        // Old databases retain their existing personal.db. New collections use stable,
        // separate stores, so private edits never appear in the public starter.
        val id = validated.info.collectionId
        val nextName = if (id.isEmpty()) "personal.db" else "personal-" +
            MessageDigest.getInstance("SHA-256").digest(id.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) } + ".db"
        val candidate = if (personalName == nextName) personal else createPersonal(nextName)
        var backup: File? = null
        var replaced = false
        var count = validated.info.count
        // Move a retired entry's personal changes with it. If both were edited,
        // retain the second edit as an independent personal entry rather than losing it.
        try {
            val db = candidate.writableDatabase
            db.beginTransaction()
            try {
                for ((old, target) in validated.aliases) {
                    if (hasEdit(db, old)) {
                        val newId = if (hasEdit(db, target)) "personal-${java.util.UUID.randomUUID()}" else target
                        db.execSQL("UPDATE edits SET id=? WHERE id=?", arrayOf(newId, old))
                        if (newId != target) db.execSQL(
                            "INSERT OR IGNORE INTO favourites SELECT ? FROM favourites WHERE entry_id=?", arrayOf(newId, old))
                    }
                }
                // Count the candidate collection inside the same transaction as alias migration.
                db.rawQuery("SELECT id,deleted FROM edits", null).use { c ->
                    while (c.moveToNext()) {
                        if (c.getString(0) in validated.ids) count--
                        if (c.getInt(1) == 0) count++
                    }
                }
                require(count <= 100000) { "This database and your personal additions exceed the 100,000 term limit." }
                if (replacement != null) {
                    if (destination.exists()) {
                        backup = File.createTempFile("previous-", ".db", destination.parentFile)
                        destination.copyTo(checkNotNull(backup), overwrite = true)
                    }
                    check(replacement.renameTo(destination)) { "Could not replace the glossary. Existing data is unchanged." }
                    replaced = true
                }
                db.setTransactionSuccessful()
            } finally { db.endTransaction() }
        } catch (error: Exception) {
            if (replaced) {
                val restored = backup?.renameTo(destination) ?: destination.delete()
                if (!restored) error.addSuppressed(IllegalStateException("Could not restore the database; backup: ${backup?.path}"))
            }
            if (candidate !== personal) candidate.close()
            throw error
        } finally {
            // Preserve a recovery copy if restoration itself failed.
            if (!replaced || backup?.exists() == false) backup?.delete()
        }
        backup?.delete()
        if (candidate !== personal) personal.close()
        personal = candidate
        personalName = nextName
        cachedInfo = validated.info.copy(count = count)
        cachedAliases = validated.aliases
    }

    private fun hasEdit(db: SQLiteDatabase, id: String): Boolean =
        db.rawQuery("SELECT 1 FROM edits WHERE id=?", arrayOf(id)).use { it.moveToFirst() }

    private val effectiveEntries = """WITH entries AS (
        SELECT e.id,e.abbreviation,e.meaning,e.notes,e.source,e.abbreviation_search,e.meaning_search,
            0 AS is_local, '' AS citation FROM main.entries e
        WHERE NOT EXISTS (SELECT 1 FROM personal.edits p WHERE p.id=e.id)
        UNION ALL
        SELECT id,abbreviation,meaning,notes,source,abbreviation_search,meaning_search,1,citation
        FROM personal.edits WHERE deleted=0
    ) """

    private fun openEffective(): SQLiteDatabase {
        personal.readableDatabase // Ensure creation/migration before attaching.
        val db = open()
        try {
            db.execSQL("ATTACH DATABASE ? AS personal", arrayOf(context.getDatabasePath(personalName).path))
            return db
        } catch (e: Exception) { db.close(); throw e }
    }

    private fun refreshCount() {
        val count = openEffective().use { db ->
            db.rawQuery(effectiveEntries + "SELECT count(*) FROM entries", null).use { it.moveToFirst(); it.getInt(0) }
        }
        cachedInfo = checkNotNull(cachedInfo).copy(count = count)
    }

    fun saveEdit(original: Term?, abbreviation: String, meaning: String, notes: String, citation: String): String {
        require(meaning.isNotBlank()) { "Enter a meaning." }
        require(listOf(abbreviation, meaning, notes, citation).all { it.length <= 100000 && '\u0000' !in it }) {
            "Each field must contain at most 100,000 characters and no NUL characters."
        }
        val id = original?.id?.let { cachedAliases[it] ?: it } ?: "personal-${java.util.UUID.randomUUID()}"
        val db = personal.writableDatabase
        val visible = db.rawQuery("SELECT deleted FROM edits WHERE id=?", arrayOf(id)).use { c ->
            if (c.moveToFirst()) c.getInt(0) == 0 else open().use { base ->
            base.rawQuery("SELECT 1 FROM entries WHERE id=?", arrayOf(id)).use { it.moveToFirst() }
            }
        }
        require(visible || info().count < 100000) { "The glossary has reached the 100,000 term limit." }
        val origin = db.rawQuery("SELECT origin_source FROM edits WHERE id=?", arrayOf(id)).use { c ->
            if (c.moveToFirst()) c.getString(0) else open().use { base ->
                base.rawQuery("SELECT source FROM entries WHERE id=?", arrayOf(id)).use { b ->
                    if (b.moveToFirst()) b.getString(0) else original?.source.orEmpty()
                }
            }
        }
        val personalSource = if (origin.isBlank()) "Personal entry" else "Personal edit"
        val source = listOf(origin, personalSource + if (citation.isBlank()) "" else ": ${citation.trim()}")
            .filter { it.isNotBlank() }.joinToString("\n")
        require(source.length <= 100000) { "The combined source references are too long." }
        // SQLite's single-statement replacement is atomic.
        check(db.insertWithOnConflict("edits", null, ContentValues().apply {
            put("id", id); put("abbreviation", abbreviation.trim()); put("meaning", meaning.trim())
            put("notes", notes.trim()); put("source", source); put("origin_source", origin); put("citation", citation.trim())
            put("abbreviation_search", normalize(abbreviation)); put("meaning_search", normalize(meaning)); put("deleted", 0)
        }, SQLiteDatabase.CONFLICT_REPLACE) != -1L) { "Could not save the term." }
        refreshCount()
        return id
    }

    fun removeTerm(term: Term) {
        if (!hasEdit(personal.writableDatabase, term.id))
            saveEdit(term, term.abbreviation, term.meaning, term.notes, term.citation)
        personal.writableDatabase.execSQL("UPDATE edits SET deleted=1 WHERE id=?", arrayOf(term.id))
        refreshCount()
    }

    fun restoreTerm(id: String) {
        val hidden = personal.readableDatabase.rawQuery("SELECT deleted FROM edits WHERE id=?", arrayOf(id)).use {
            it.moveToFirst() && it.getInt(0) != 0
        }
        val inBase = open().use { db -> db.rawQuery("SELECT 1 FROM entries WHERE id=?", arrayOf(id)).use { it.moveToFirst() } }
        require(!hidden || !inBase || info().count < 100000) { "The glossary has reached the 100,000 term limit." }
        personal.writableDatabase.delete("edits", "id=?", arrayOf(id))
        refreshCount()
    }

    fun undoRemoval(id: String) {
        val hidden = personal.readableDatabase.rawQuery("SELECT deleted FROM edits WHERE id=?", arrayOf(id)).use {
            it.moveToFirst() && it.getInt(0) != 0
        }
        require(!hidden || info().count < 100000) { "The glossary has reached the 100,000 term limit." }
        personal.writableDatabase.execSQL("UPDATE edits SET deleted=0 WHERE id=?", arrayOf(id))
        refreshCount()
    }

    fun personalChanges(): List<Term> {
        val saved = savedIds()
        return personal.readableDatabase.rawQuery(
        "SELECT id,abbreviation,meaning,notes,source,citation,deleted FROM edits ORDER BY abbreviation_search,meaning_search,id", null
    ).use { c ->
        buildList {
            while (c.moveToNext()) add(Term(c.getString(0), c.getString(1), c.getString(2), c.getString(3), c.getString(4),
                favourite = c.getString(0) in saved, local = true, citation = c.getString(5), deleted = c.getInt(6) != 0))
        }
        }
    }

    // Export a standalone, import-compatible snapshot. Favourites remain private to the device.
    fun exportDatabase(uri: Uri) {
        val temp = File.createTempFile("export-", ".db", context.cacheDir)
        try {
            destination.copyTo(temp, overwrite = true)
            SQLiteDatabase.openDatabase(temp.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.beginTransaction()
                try {
                    db.delete("entries", null, null)
                    val ids = hashSetOf<String>()
                    openEffective().use { active ->
                        active.rawQuery(effectiveEntries + "SELECT id,abbreviation,meaning,notes,source,abbreviation_search,meaning_search FROM entries", null).use { c ->
                            val fields = listOf("id", "abbreviation", "meaning", "notes", "source", "abbreviation_search", "meaning_search")
                            while (c.moveToNext()) {
                                ids.add(c.getString(0))
                                db.insertOrThrow("entries", null, ContentValues().apply { fields.forEachIndexed { i, field -> put(field, c.getString(i)) } })
                            }
                        }
                    }
                    fun metadata(key: String, value: String) {
                        db.insertWithOnConflict("metadata", null, ContentValues().apply { put("key", key); put("value", value) }, SQLiteDatabase.CONFLICT_REPLACE)
                    }
                    metadata("entry_count", ids.size.toString())
                    metadata("dataset_version", "personal-${java.util.UUID.randomUUID()}")
                    metadata("entry_aliases", org.json.JSONObject(cachedAliases.filterValues { it in ids }).toString())
                    db.delete("metadata", "key=?", arrayOf("content_sha256")) // The Python content digest no longer applies.
                    db.setTransactionSuccessful()
                } finally { db.endTransaction() }
                db.execSQL("VACUUM")
            }
            validate(temp)
            require(temp.length() <= 64L * 1024 * 1024) { "Export exceeds the 64 MB import limit." }
            requireNotNull(context.contentResolver.openOutputStream(uri, "wt")) { "Cannot write selected file." }.use { out ->
                temp.inputStream().use { it.copyTo(out) }
            }
        } finally { temp.delete() }
    }

    private fun replace(temp: File) {
        val validatedInfo = validate(temp)
        publish(validatedInfo, temp)
    }

    private fun installBundle(hash: String? = null) {
        val temp = File.createTempFile("bundle-", ".db", destination.parentFile)
        try {
            context.assets.open("glossary.db").use { input -> temp.outputStream().use { input.copyTo(it) } }
            replace(temp)
            prefs.edit(commit = true) {
                putBoolean("imported", false)
                if (hash != null) putString("bundleHash", hash) else remove("bundleHash")
            }
        } finally { temp.delete() }
    }

    fun useBundled() { installBundle() }

    fun importDatabase(uri: Uri) {
        val temp = File.createTempFile("import-", ".db", destination.parentFile)
        try {
            requireNotNull(context.contentResolver.openInputStream(uri)) { "Cannot open selected file." }.use { input ->
                temp.outputStream().use { output ->
                    val buffer = ByteArray(8192)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        require(total <= 64L * 1024 * 1024) { "Database exceeds the 64 MB import limit." }
                        output.write(buffer, 0, n)
                    }
                }
            }
            replace(temp)
            prefs.edit(commit = true) { putBoolean("imported", true) }
        } finally { temp.delete() }
    }

    // No disk access: initialized once and refreshed when the active database changes.
    fun info(): GlossaryInfo = checkNotNull(cachedInfo) { "Initialize the glossary first." }

    fun toggleFavourite(term: Term) {
        val db = personal.writableDatabase
        if (term.favourite) {
            for (id in listOf(term.id) + cachedAliases.filterValues { it == term.id }.keys)
                db.delete("favourites", "entry_id=?", arrayOf(id))
        }
        else db.insertWithOnConflict("favourites", null, ContentValues().apply {
            put("entry_id", term.id)
        }, SQLiteDatabase.CONFLICT_IGNORE)
    }

    private fun savedIds(): Set<String> {
        val saved = hashSetOf<String>()
        personal.readableDatabase.rawQuery("SELECT entry_id FROM favourites", null).use { c ->
            while (c.moveToNext()) saved.add(c.getString(0))
        }
        saved.toList().forEach { old -> cachedAliases[old]?.let { saved.add(it) } }
        return saved
    }

    fun search(query: String, favouritesOnly: Boolean): SearchResult {
        val saved = savedIds()
        val q = normalize(query)
        val escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        // In favourite mode filter before the limit so matches after the first 200 are retained.
        val projected = searchSql.replace("notes, source FROM entries", "notes, source, is_local, citation FROM entries")
        val sql = effectiveEntries + if (favouritesOnly) projected.replace("LIMIT 201", "") else projected
        val terms = mutableListOf<Term>()
        openEffective().use { db ->
            db.rawQuery(sql, arrayOf("%$escaped%", "%$escaped%", q, "$escaped%", "$escaped%")).use { c ->
                while (c.moveToNext() && terms.size < 201) {
                    val id = c.getString(0)
                    if (!favouritesOnly || id in saved) terms.add(Term(id, c.getString(1), c.getString(2),
                        c.getString(3), c.getString(4), id in saved, c.getInt(5) != 0, c.getString(6)))
                }
            }
        }
        return SearchResult(terms.take(200), terms.size > 200)
    }

    override fun close() { personal.close(); cachedInfo = null; cachedAliases = emptyMap() }

    companion object {
        fun normalize(value: String): String = Normalizer.normalize(value.trim(), Normalizer.Form.NFD)
            .replace(Regex("\\p{Mn}+"), "").lowercase(Locale.ROOT)
    }
}
