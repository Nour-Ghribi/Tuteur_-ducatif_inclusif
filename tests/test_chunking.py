from tuteur.chunking import chunk_document, split_text
from tuteur.ingestion import Document, Page


def test_short_text_is_one_chunk():
    assert split_text("Une phrase.", size=100, overlap=10) == ["Une phrase."]


def test_chunks_respect_size():
    text = "\n\n".join(f"Paragraphe numéro {i}. " * 5 for i in range(20))
    chunks = split_text(text, size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_overlap_repeats_end_of_previous_chunk():
    text = "\n\n".join(f"Phrase {i} " + "x" * 80 for i in range(10))
    chunks = split_text(text, size=200, overlap=40)
    assert chunks[0][-40:] in chunks[1]


def test_very_long_sentence_is_cut():
    chunks = split_text("a" * 1000, size=300, overlap=0)
    assert [len(c) for c in chunks] == [300, 300, 300, 100]


def test_chunk_ids_are_stable_and_carry_page():
    doc = Document("abc", "cours.pdf", [Page(1, "Texte page un."), Page(2, "Texte page deux.")])
    chunks = chunk_document(doc, size=100, overlap=0)
    assert [c.id for c in chunks] == ["abc-p1-c0", "abc-p2-c0"]
    assert chunks[1].metadata == {"doc_id": "abc", "source": "cours.pdf", "page": 2, "has_images": False}
