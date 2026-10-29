from tuteur.citations import check_citations, cited_pages, strip_invalid_citations
from tuteur.prompts import load_prompt


def test_cited_pages_formats():
    assert cited_pages("[p. 3]") == [3]
    assert cited_pages("[p. 1, 3]") == [1, 3]
    assert cited_pages("[pages 2-4]") == [2, 3, 4]
    assert cited_pages("[p. 1–2]") == [1, 2]


def test_check_detects_page_outside_passages():
    check = check_citations("Le MVP génère 5 à 10 quiz [p. 8]. DVC versionne [p. 3].", {1, 2, 3, 4})
    assert check.cited == [8, 3]
    assert check.invalid == [8]
    assert check.validity == 0.5


def test_lenticular_brackets_are_citations_and_get_normalized():
    text = "La respiration a lieu jour et nuit【p. 1】."
    assert check_citations(text, {1}).cited == [1]
    assert strip_invalid_citations(text, {1}) == "La respiration a lieu jour et nuit[p. 1]."


def test_no_citation():
    check = check_citations("Le cours n'en parle pas.", {1})
    assert check.n_citations == 0 and check.validity is None


def test_strip_invalid_keeps_valid_pages_and_clean_punctuation():
    text = "Le MVP génère 5 à 10 quiz [p. 8]. DVC versionne [p. 3, 9]."
    assert strip_invalid_citations(text, {1, 2, 3, 4}) == "Le MVP génère 5 à 10 quiz. DVC versionne [p. 3]."


def test_prompt_versions_resolve_to_latest_at_or_below():
    assert load_prompt("answer", 3).tag == "answer@v3"
    assert load_prompt("answer", 2).tag == "answer@v2"
    assert load_prompt("quiz", 3).tag == "quiz@v2"  # pas de quiz v3 : on garde la v2


def test_v3_context_format_labels_pages():
    from tuteur.generation import format_context
    from tuteur.vectorstore import SearchResult

    results = [SearchResult("a", "8. Valeur ajoutée", {"page": 4, "source": "projet.pdf"}, 0.1)]
    assert format_context(results, load_prompt("answer", 3).context_format) == (
        "=== PASSAGE 1 — page 4 ===\n8. Valeur ajoutée")
    assert format_context(results) == "[p. 4] 8. Valeur ajoutée"  # v1/v2 inchangés


def test_styles_v4_only_in_snapshot_4():
    from tuteur.prompts import load_styles

    assert load_styles(3)["version"] == 2  # le snapshot v3 déjà évalué ne change pas
    assert load_styles(4)["version"] == 4
    assert "N'invente aucun exemple" in load_styles(4)["simplifie"]


def test_styles_v5_asks_for_every_element():
    from tuteur.prompts import load_styles

    assert load_styles(4)["version"] == 4
    assert "donne-les tous" in load_styles(5)["simplifie"]
