SELECT id, abbreviation, meaning, notes, source FROM entries
WHERE abbreviation_search LIKE ? ESCAPE '\' OR meaning_search LIKE ? ESCAPE '\'
ORDER BY CASE
    WHEN abbreviation_search = ? AND abbreviation_search != '' THEN 0
    WHEN abbreviation_search LIKE ? ESCAPE '\' AND abbreviation_search != '' THEN 1
    WHEN meaning_search LIKE ? ESCAPE '\' THEN 2
    ELSE 3 END,
    abbreviation_search, meaning_search, id
LIMIT 201
