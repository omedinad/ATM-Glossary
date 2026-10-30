// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import android.content.res.Configuration
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Parcelable
import android.net.Uri
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.os.BundleCompat
import androidx.core.widget.doAfterTextChanged
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.mcxa.icaoglossary.databinding.ActivityMainBinding
import org.mcxa.icaoglossary.databinding.DialogAboutBinding
import org.mcxa.icaoglossary.databinding.DialogEditBinding
import org.mcxa.icaoglossary.databinding.DialogTermBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var repository: GlossaryRepository
    private val worker = DatabaseWorker.executor
    private val main = Handler(Looper.getMainLooper())
    private var generation = 0
    private var ready = false
    private var alive = true
    private val adapter = TermAdapter(::showTerm)
    private var editor: DialogEditBinding? = null
    private var editingTerm: Term? = null
    private var pendingDraft: Bundle? = null
    private var pendingFile: Pair<Uri, Boolean>? = null // URI and whether this is an export.
    private var listState: Parcelable? = null
    private var lastSearch: Pair<String, Boolean>? = null
    private val pickDatabase = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) { pendingFile = uri to false; consumePendingFile() }
    }
    private val saveDatabase = registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri != null) { pendingFile = uri to true; consumePendingFile() }
    }

    /** Sets up the screen, restores saved UI state, and loads the glossary in the background. */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        pendingDraft = savedInstanceState?.getBundle("editor")
        listState = savedInstanceState?.let { BundleCompat.getParcelable(it, "resultsState", Parcelable::class.java) }
        savedInstanceState?.getString("fileUri")?.let {
            pendingFile = Uri.parse(it) to savedInstanceState.getBoolean("fileExport")
        }
        setContentView(binding.root)
        val dark = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        WindowCompat.getInsetsController(window, binding.root).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val keyboard = insets.getInsets(WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, keyboard.bottom))
            // Leave a usable list viewport on short/landscape windows with an IME.
            val available = resources.configuration.screenHeightDp - keyboard.bottom / resources.displayMetrics.density
            val compact = insets.isVisible(WindowInsetsCompat.Type.ime()) && available < 300
            binding.toolbar.visibility = if (compact) View.GONE else View.VISIBLE
            binding.favourites.visibility = if (compact) View.GONE else View.VISIBLE
            insets
        }
        setSupportActionBar(binding.toolbar)
        binding.results.layoutManager = LinearLayoutManager(this)
        adapter.stateRestorationPolicy = RecyclerView.Adapter.StateRestorationPolicy.PREVENT_WHEN_EMPTY
        binding.results.adapter = adapter
        binding.results.addOnScrollListener(
            object : RecyclerView.OnScrollListener() {
                /** Hides the keyboard when the user starts dragging the results. */
                override fun onScrollStateChanged(recyclerView: RecyclerView, newState: Int) {
                    if (newState == RecyclerView.SCROLL_STATE_DRAGGING) dismissKeyboard()
                }
            },
        )
        binding.results.setOnGenericMotionListener { _, event ->
            if (event.action == MotionEvent.ACTION_SCROLL) dismissKeyboard()
            false // RecyclerView still handles the wheel/trackpad event.
        }
        binding.search.setText(savedInstanceState?.getString("query", "") ?: "")
        binding.favourites.isChecked = savedInstanceState?.getBoolean("favourites", false) ?: false
        binding.search.doAfterTextChanged { scheduleSearch() }
        binding.search.setOnEditorActionListener { _, action, event ->
            if (action == EditorInfo.IME_ACTION_SEARCH || action == EditorInfo.IME_ACTION_DONE ||
                (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                dismissKeyboard()
                true
            } else false
        }
        binding.clear.setOnClickListener { binding.search.text?.clear() }
        binding.favourites.setOnCheckedChangeListener { _, _ -> scheduleSearch() }
        repository = GlossaryRepository(applicationContext)
        worker.execute {
            try {
                repository.initialize()
                main.post { if (alive) {
                    ready = true; invalidateOptionsMenu()
                    if (!consumePendingFile()) scheduleSearch()
                    pendingDraft?.let { draft ->
                        val term = if (draft.containsKey("id")) Term(draft.getString("id")!!,
                            draft.getString("abbreviation", ""), draft.getString("meaning", ""),
                            draft.getString("notes", ""), draft.getString("source", ""),
                            local = draft.getBoolean("local"), citation = draft.getString("citation", "")) else null
                        showEditor(term, draft)
                        pendingDraft = null
                    }
                } }
            } catch (e: Exception) { main.post { if (alive) showError(e) } }
        }
    }

    /** Releases search-field focus and hides the on-screen keyboard. */
    private fun dismissKeyboard() {
        if (binding.search.hasFocus()) binding.root.requestFocus()
        WindowCompat.getInsetsController(window, binding.root).hide(WindowInsetsCompat.Type.ime())
    }

    /** Starts a queued import or export when ready, returning whether an operation was started. */
    private fun consumePendingFile(): Boolean {
        if (!ready) return false
        val (uri, export) = pendingFile ?: return false
        pendingFile = null
        if (export) changeData(R.string.exported) { repository.exportDatabase(uri) }
        else changeData(resetList = true) { repository.importDatabase(uri) }
        return true
    }

    /** Shows or hides the loading bar without moving the results, and sets the loading message when shown. */
    private fun setLoading(loading: Boolean) {
        // Reserve the bar's space so finishing a load never shifts the results.
        binding.loadingProgress.visibility = if (loading) View.VISIBLE else View.INVISIBLE
        if (loading) binding.status.setText(R.string.loading)
    }

    /**
     * Waits briefly for typing to settle, then searches in the background and ignores stale results.
     * [force] refreshes an unchanged query while preserving its scroll position.
     */
    private fun scheduleSearch(force: Boolean = false) {
        if (!ready) return
        val query = binding.search.text.toString()
        val onlySaved = binding.favourites.isChecked
        val key = query to onlySaved
        if (!force && key == lastSearch) return
        val resetPosition = key != lastSearch
        lastSearch = key
        val request = ++generation
        setLoading(loading = true)
        main.postDelayed({
            if (alive && request == generation) worker.execute {
                try {
                    val result = repository.search(query, onlySaved)
                    main.post {
                        if (alive && request == generation) {
                            setLoading(loading = false)
                            adapter.submitList(result.terms) {
                                if (alive && request == generation) {
                                    val state = listState
                                    if (state != null) {
                                        binding.results.layoutManager?.onRestoreInstanceState(state)
                                        listState = null
                                    } else if (resetPosition) binding.results.scrollToPosition(0)
                                }
                            }
                            binding.status.text = when {
                                result.more -> getString(R.string.results_limited)
                                result.terms.isEmpty() -> getString(if (onlySaved) R.string.no_favourites else R.string.no_matches)
                                else -> resources.getQuantityString(R.plurals.results, result.terms.size, result.terms.size)
                            }
                        }
                    }
                } catch (e: Exception) { main.post { if (alive && request == generation) showError(e) } }
            }
        }, 150)
    }

    /** Opens a term's details with actions for sources, favourites, editing, and removal. */
    private fun showTerm(term: Term) {
        if (!ready) return
        val view = DialogTermBinding.inflate(layoutInflater)
        view.meaning.text = term.meaning
        view.notes.text = term.notes
        view.notes.visibility = if (term.notes.isBlank()) View.GONE else View.VISIBLE
        view.provenance.text = SourceCatalog.summary(term.source)
        val dialog = AlertDialog.Builder(this)
            .setTitle(term.abbreviation.ifBlank { term.meaning })
            .setView(view.root)
            .setPositiveButton(R.string.close, null)
            .setNegativeButton(R.string.edit_term) { _, _ -> showEditor(term) }.create()
        view.sources.setOnClickListener { showSources(term.source) }
        view.favourite.setText(if (term.favourite) R.string.remove_favourite else R.string.save_favourite)
        view.favourite.visibility = if (term.deleted) View.GONE else View.VISIBLE
        view.favourite.setOnClickListener { dialog.dismiss(); changeData { repository.toggleFavourite(term) } }
        view.remove.setText(if (term.deleted) R.string.restore_term else R.string.remove_term)
        view.remove.setOnClickListener {
            dialog.dismiss()
            if (term.deleted) changeData { repository.undoRemoval(term.id) }
            else AlertDialog.Builder(this).setTitle(R.string.remove_term).setMessage(R.string.remove_help)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.remove_term) { _, _ -> changeData { repository.removeTerm(term) } }.show()
        }
        view.reset.visibility = if (term.local) android.view.View.VISIBLE else android.view.View.GONE
        view.reset.setOnClickListener {
            AlertDialog.Builder(this).setTitle(R.string.discard_edit).setMessage(R.string.discard_help)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.discard_edit) { _, _ -> dialog.dismiss(); changeData { repository.restoreTerm(term.id) } }.show()
        }
        dialog.show()
    }

    /** Opens the add/edit form, restores any [draft], and saves changes in the background. */
    private fun showEditor(term: Term?, draft: Bundle? = null) {
        if (!ready) return
        val form = DialogEditBinding.inflate(layoutInflater)
        // Allocate a stable ID before saving so recreating the activity during a save cannot add a duplicate.
        val editTarget = term ?: Term("personal-${java.util.UUID.randomUUID()}", "", "", "", "", local = true)
        editingTerm = editTarget
        editor = form
        form.abbreviation.setText(draft?.getString("abbreviation") ?: term?.abbreviation.orEmpty())
        form.meaning.setText(draft?.getString("meaning") ?: term?.meaning.orEmpty())
        form.notes.setText(draft?.getString("notes") ?: term?.notes.orEmpty())
        form.citation.setText(draft?.getString("citation") ?: term?.citation.orEmpty())
        val dialog = AlertDialog.Builder(this).setTitle(if (term == null) R.string.add_term else R.string.edit_term)
            .setView(form.root).setNegativeButton(R.string.cancel, null).setPositiveButton(R.string.save, null).create()
        dialog.setOnDismissListener { if (editor === form) { editor = null; editingTerm = null } }
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (form.meaning.text.isNullOrBlank()) {
                    form.meaning.error = getString(R.string.meaning_required)
                    form.meaning.requestFocus()
                    return@setOnClickListener
                }
                val abbreviation = form.abbreviation.text.toString()
                val meaning = form.meaning.text.toString()
                val notes = form.notes.text.toString()
                val citation = form.citation.text.toString()
                ready = false; ++generation; invalidateOptionsMenu()
                setLoading(true)
                dialog.setCancelable(false)
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = false
                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).isEnabled = false
                worker.execute {
                    val error = runCatching { repository.saveEdit(editTarget, abbreviation, meaning, notes, citation) }.exceptionOrNull()
                    main.post {
                        if (alive) {
                            ready = true; invalidateOptionsMenu(); scheduleSearch(force = true)
                            if (error == null) dialog.dismiss() else {
                                dialog.setCancelable(true)
                                dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = true
                                dialog.getButton(AlertDialog.BUTTON_NEGATIVE).isEnabled = true
                                showError(error)
                            }
                        }
                    }
                }
            }
        }
        dialog.show()
    }

    /** Shows selectable information in a dialog with clickable web links. */
    private fun showText(title: CharSequence, text: CharSequence) {
        val dialog = AlertDialog.Builder(this).setTitle(title).setMessage(text).setPositiveButton(R.string.close, null).show()
        dialog.findViewById<android.widget.TextView>(android.R.id.message)?.apply {
            setTextIsSelectable(true)
            if (text !is android.text.Spanned) androidx.core.text.util.LinkifyCompat.addLinks(this, android.text.util.Linkify.WEB_URLS)
            movementMethod = android.text.method.LinkMovementMethod.getInstance()
        }
    }

    /** Groups a term's sources into a short list with access to each full citation. */
    private fun showSources(raw: String) {
        val groups = SourceCatalog.groups(raw)
        AlertDialog.Builder(this).setTitle(R.string.sources)
            .setItems(groups.map { it.source.label }.toTypedArray()) { _, index ->
                val group = groups[index]
                AlertDialog.Builder(this).setTitle(group.source.label)
                    .setMessage(group.source.description + "\n\n" + group.locations)
                    .setPositiveButton(R.string.close, null)
                    .setNeutralButton(R.string.full_citation) { _, _ -> showText(group.source.label, group.references.joinToString("\n\n")) }.show()
            }.setPositiveButton(R.string.close, null).show()
    }

    /** Shows the app version, cached term count, and links to sources, credits, and help. */
    private fun showAbout() {
        worker.execute {
            val info = try { repository.info() } // Cached; no SQLite query when About opens.
                catch (e: Exception) { main.post { if (alive) showError(e) }; return@execute }
            main.post {
                if (alive) {
                    val view = DialogAboutBinding.inflate(layoutInflater)
                    val version = packageManager.getPackageInfo(packageName, 0).versionName.orEmpty()
                    view.version.text = getString(R.string.app_version, version)
                    view.count.text = getString(R.string.about_count, java.text.NumberFormat.getIntegerInstance().format(info.count))
                    view.sources.setOnClickListener {
                        AlertDialog.Builder(this).setTitle(R.string.sources_editions)
                            .setItems((info.sources.map { it.label } + getString(R.string.active_glossary)).toTypedArray()) { _, index ->
                                if (index < info.sources.size) {
                                    val source = info.sources[index]
                                    showText(source.label, source.description)
                                } else showText(getString(R.string.active_glossary), getString(R.string.active_glossary_body, info.title, info.version))
                            }.setPositiveButton(R.string.close, null).show()
                    }
                    view.credits.setOnClickListener {
                        showText(getString(R.string.credits), android.text.SpannableStringBuilder()
                            .append(getText(R.string.historical_credits)).append("\n\n")
                            .append(getText(R.string.about_contents)).append("\n\n").append(getText(R.string.about_omd))
                            .append("\n\n").append(getText(R.string.current_icon_credit)))
                    }
                    view.help.setOnClickListener { showText(getString(R.string.editing_backups), getString(R.string.editing_help)) }
                    AlertDialog.Builder(this).setTitle(R.string.app_name).setView(view.root)
                        .setPositiveButton(R.string.close, null).show()
                }
            }
        }
    }

    /** Loads personal changes in the background and lists them, including removed terms. */
    private fun showChanges() {
        worker.execute {
            val changes = try { repository.personalChanges() }
                catch (e: Exception) { main.post { if (alive) showError(e) }; return@execute }
            main.post {
                if (alive) {
                    if (changes.isEmpty()) showText(getString(R.string.my_changes), getString(R.string.no_changes))
                    else AlertDialog.Builder(this).setTitle(R.string.my_changes)
                        .setItems(changes.map { (if (it.deleted) getString(R.string.removed_prefix) else "") +
                            it.abbreviation.ifBlank { it.meaning }.take(60) + " — " + it.meaning.take(100) }.toTypedArray()) { _, index ->
                            showTerm(changes[index])
                        }.setPositiveButton(R.string.close, null).show()
                }
            }
        }
    }

    /**
     * Runs [action] on the database worker, then refreshes results and reports success or failure.
     * [resetList] clears the previous collection's results and scroll position before starting.
     */
    private fun changeData(success: Int = R.string.data_ready, resetList: Boolean = false, action: () -> Unit) {
        ready = false
        ++generation
        invalidateOptionsMenu()
        setLoading(true)
        binding.results.isEnabled = false
        if (resetList) { adapter.submitList(emptyList()); lastSearch = null; listState = null }
        worker.execute {
            val error = runCatching(action).exceptionOrNull()
            main.post {
                if (alive) {
                    ready = true
                    binding.results.isEnabled = true
                    invalidateOptionsMenu()
                    scheduleSearch(force = true)
                    if (error != null) showError(error)
                    else Toast.makeText(this, success, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    /** Hides the loading bar and displays the failure in the status line and a toast. */
    private fun showError(error: Throwable) {
        setLoading(false)
        val message = getString(R.string.operation_failed, error.message ?: error.javaClass.simpleName)
        binding.status.text = message
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    /** Adds the glossary editing, import/export, restore, and About menu items. */
    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 4, 0, R.string.add_term)
        menu.add(0, 5, 1, R.string.my_changes)
        menu.add(0, 6, 2, R.string.export_db)
        menu.add(0, 1, 3, R.string.import_db)
        menu.add(0, 2, 4, R.string.restore_db)
        menu.add(0, 3, 5, R.string.about)
        return true
    }
    /** Enables menu actions only when the glossary is ready. */
    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        for (id in 1..6) menu.findItem(id)?.isEnabled = ready
        return super.onPrepareOptionsMenu(menu)
    }
    /** Opens the selected glossary action or passes unhandled menu items to the activity. */
    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> pickDatabase.launch(arrayOf("*/*"))
            2 -> changeData(resetList = true) { repository.useBundled() }
            3 -> showAbout()
            4 -> showEditor(null)
            5 -> showChanges()
            6 -> saveDatabase.launch("ATM-Glossary-personal.db")
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }
    /** Saves the search, list position, pending file operation, and editor draft for screen recreation. */
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("query", binding.search.text.toString())
        outState.putBoolean("favourites", binding.favourites.isChecked)
        outState.putParcelable("resultsState", binding.results.layoutManager?.onSaveInstanceState())
        pendingFile?.let { (uri, export) -> outState.putString("fileUri", uri.toString()); outState.putBoolean("fileExport", export) }
        editor?.let { form ->
            outState.putBundle("editor", Bundle().apply {
                editingTerm?.let { putString("id", it.id); putString("source", it.source); putBoolean("local", it.local) }
                putString("abbreviation", form.abbreviation.text.toString()); putString("meaning", form.meaning.text.toString())
                putString("notes", form.notes.text.toString()); putString("citation", form.citation.text.toString())
            })
        }
        super.onSaveInstanceState(outState)
    }
    /** Cancels this screen's callbacks and closes its repository after queued database work finishes. */
    override fun onDestroy() {
        alive = false
        ++generation
        main.removeCallbacksAndMessages(null)
        worker.execute { repository.close() }
        super.onDestroy()
    }
}
