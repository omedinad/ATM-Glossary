// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

/** Presentation only. The unabridged citation is kept in every entry and export. */
object SourceCatalog {
    data class Source(val label: String, val description: String)
    data class Group(val source: Source, val references: List<String>) {
        val locations: String get() = references.joinToString("\n\n") {
            if (it.startsWith("Wikipedia contributors;") && "; revision " in it)
                "Revision " + it.substringAfter("; revision ").substringBefore("; retrieved")
            else it
        }
    }
    private fun identify(line: String): Source = when {
        line.startsWith("Wikipedia contributors;") -> Source("Wikipedia", "Wikipedia contributors. Adapted under CC BY-SA 4.0. The full citation identifies the article revision, table row and licence.")
        line.startsWith("Personal edit") -> Source("Personal edit", "Edited on this device. Retained citations do not certify revised wording.")
        line.startsWith("Personal entry") -> Source("Personal entry", "Added on this device, with any reference supplied by its author.")
        else -> Source(line.substringBefore(';').take(80), "Reference supplied with this entry. See its full citation for provenance and any reuse terms.")
    }
    fun groups(raw: String): List<Group> = raw.lines().map(String::trim).filter(String::isNotEmpty)
        .distinct().groupBy(::identify).map { (source, references) -> Group(source, references) }
    fun summary(raw: String, limit: Int = Int.MAX_VALUE): String {
        val sources = groups(raw).sortedByDescending { it.source.label.startsWith("Personal") }
        return sources.take(limit).joinToString(" · ") { it.source.label } +
            if (sources.size > limit) " · +${sources.size - limit}" else ""
    }
}
