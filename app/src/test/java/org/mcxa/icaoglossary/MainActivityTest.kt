// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import android.app.Activity
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.os.Bundle
import android.os.Looper
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import org.robolectric.fakes.RoboMenuItem
import org.robolectric.shadows.ShadowDialog
import java.io.File
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class MainActivityTest {
    private var controller: ActivityController<MainActivity>? = null
    private val activity get() = checkNotNull(controller).get()
    private val results get() = activity.findViewById<RecyclerView>(R.id.results)
    private val manager get() = results.layoutManager as LinearLayoutManager

    private fun layout() {
        val root = activity.findViewById<View>(R.id.container)
        root.measure(View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(1800, View.MeasureSpec.EXACTLY))
        root.layout(0, 0, 1080, 1800)
    }
    private fun awaitIdle(condition: () -> Boolean = {
        results.adapter!!.itemCount > 0 && activity.findViewById<TextView>(R.id.status).text != activity.getString(R.string.loading)
    }) {
        repeat(200) {
            DatabaseWorker.executor.submit {}.get(10, TimeUnit.SECONDS)
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(200))
            layout()
            if (condition()) return
            Thread.sleep(10) // Allow ListAdapter's background diff to finish.
        }
        fail("Activity did not finish its pending work")
    }
    private fun launch() {
        controller=Robolectric.buildActivity(MainActivity::class.java).setup()
        awaitIdle()
    }
    @After fun cleanup() {
        controller?.pause()?.stop()?.destroy()
        DatabaseWorker.executor.submit {}.get(10,TimeUnit.SECONDS)
    }

    @Test fun favouriteRefreshKeepsTheScrolledPosition() {
        launch()
        manager.scrollToPositionWithOffset(25, 0);layout()
        val first=manager.findFirstVisibleItemPosition()
        assertEquals(25,first)
        val id=(results.adapter as TermAdapter).currentList[first].id
        results.findViewHolderForAdapterPosition(first)!!.itemView.performClick()
        ShadowDialog.getLatestDialog().findViewById<View>(R.id.favourite).performClick()
        awaitIdle { (results.adapter as TermAdapter).currentList.any { it.id==id && it.favourite } }
        assertEquals(first,manager.findFirstVisibleItemPosition())
    }

    @Test fun recreatedActivityRestoresListPositionAfterAsyncLoad() {
        launch()
        manager.scrollToPositionWithOffset(25, 0);layout()
        val state=Bundle()
        controller!!.saveInstanceState(state).pause().stop().destroy()
        controller=Robolectric.buildActivity(MainActivity::class.java).create(state).start().resume().visible()
        awaitIdle()
        assertEquals(25,manager.findFirstVisibleItemPosition())
    }

    @Test fun searchActionReleasesKeyboardFocus() {
        launch()
        val search=activity.findViewById<EditText>(R.id.search)
        search.requestFocus()
        assertTrue(search.hasFocus())
        search.onEditorAction(EditorInfo.IME_ACTION_SEARCH)
        assertFalse(search.hasFocus())
        assertTrue(results.isVerticalScrollBarEnabled)
    }

    @Test fun pickerResultDuringRecreationIsImportedAfterInitialization() {
        launch()
        val picked=File(activity.cacheDir,"picker.db")
        activity.assets.open("glossary.db").use { input -> picked.outputStream().use { input.copyTo(it) } }
        SQLiteDatabase.openDatabase(picked.path,null,SQLiteDatabase.OPEN_READWRITE).use {
            it.execSQL("UPDATE metadata SET value='picker-result' WHERE key='dataset_version'")
        }
        activity.onOptionsItemSelected(RoboMenuItem(1))
        val request=shadowOf(activity).nextStartedActivityForResult
        val state=Bundle()
        controller!!.saveInstanceState(state).pause().stop().destroy()
        val release=CountDownLatch(1)
        DatabaseWorker.executor.execute { check(release.await(10,TimeUnit.SECONDS)) }
        try {
            controller=Robolectric.buildActivity(MainActivity::class.java).create(state).start().resume().visible()
            activity.activityResultRegistry.dispatchResult(request.requestCode,Activity.RESULT_OK,Intent().setData(Uri.fromFile(picked)))
        } finally { release.countDown() }
        awaitIdle()
        SQLiteDatabase.openDatabase(activity.getDatabasePath("glossary.db").path,null,SQLiteDatabase.OPEN_READONLY).use { db ->
            db.rawQuery("SELECT value FROM metadata WHERE key='dataset_version'",null).use {
                assertTrue(it.moveToFirst());assertEquals("picker-result",it.getString(0))
            }
        }
    }
}
