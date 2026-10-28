// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import org.junit.Assert.assertEquals
import org.junit.Test

class SearchNormalizationTest {
    @Test fun accentsAndCaseMatchImportedSearchFields() {
        assertEquals("cafe", GlossaryRepository.normalize(" CAFÉ "))
        assertEquals("ads-b", GlossaryRepository.normalize("ADS-B"))
        assertEquals("100%_test", GlossaryRepository.normalize("100%_TEST"))
    }
}
