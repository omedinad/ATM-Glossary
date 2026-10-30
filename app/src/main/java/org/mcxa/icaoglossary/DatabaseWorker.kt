// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import java.util.concurrent.Executors

/** Serializes database work across activity recreation as well as within one screen. */
internal object DatabaseWorker {
    val executor = Executors.newSingleThreadExecutor()
}
