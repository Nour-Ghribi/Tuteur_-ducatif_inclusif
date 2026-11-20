from tuteur.lexical import BM25, rrf, tokenize


def test_tokenize_normalizes_french():
    assert tokenize("Les Stomates sont des orifices") == ["stomate", "orifice"]
    assert tokenize("Générer 5 à 10 quiz") == ["generer", "5", "10", "quiz"]


def test_bm25_prefers_document_with_rare_query_terms():
    docs = [
        "La photosynthèse se déroule dans les feuilles.",
        "Indexation RAG et génération de 5 à 10 quiz par chapitre.",
        "Le MLOps versionne les données avec DVC.",
    ]
    scores = BM25(docs).scores("Combien de quiz par chapitre ?")
    assert max(range(3), key=scores.__getitem__) == 1
    assert scores[0] == scores[2] == 0


def test_rrf_rewards_agreement_between_rankings():
    fused = rrf([["a", "b", "c"], ["b", "c", "a"]])
    assert [doc for doc, _ in fused][0] == "b"  # 2e + 1er bat 1er + 3e
