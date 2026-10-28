// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import org.junit.Assert.*
import org.junit.Test

class SourceCatalogTest {
    /** Checks that source summaries remove duplicate citations while retaining attribution and distinct references. */
    @Test fun sourcesGroupWithoutLosingAttribution() {
        val first="Wikipedia contributors; Example article; row 1; CC BY-SA 4.0"
        val second=first.replace("row 1","row 2")
        val raw="$first\n$second\n$first\nPersonal edit: My notebook"
        val groups=SourceCatalog.groups(raw)
        assertEquals(2,groups.size)
        assertEquals(listOf(first,second),groups.first().references)
        assertEquals("Personal edit · Wikipedia",SourceCatalog.summary(raw))
        assertEquals("Personal edit · +1",SourceCatalog.summary(raw,1))
        assertTrue(groups.first().locations.contains("CC BY-SA 4.0"))
    }
    /** Checks that custom citations keep their source labels and blank input produces no summary. */
    @Test fun customSourcesKeepTheirOwnLabels() {
        assertEquals("My handbook",SourceCatalog.summary("My handbook; page 12"))
        assertEquals("",SourceCatalog.summary("\n"))
    }
}
