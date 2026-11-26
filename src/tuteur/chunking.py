"""Découpage du texte en passages (chunks) avec chevauchement, page par page."""

import re
from dataclasses import dataclass

from tuteur.ingestion import Document


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Regroupe les paragraphes jusqu'à `size` caractères ; coupe les paragraphes trop longs
    sur les fins de phrase. Les `overlap` derniers caractères sont repris au chunk suivant."""
    text = re.sub(r"[ \t]+", " ", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    pieces: list[str] = []
    for p in paragraphs:
        if len(p) <= size:
            pieces.append(p)
        else:
            pieces.extend(s for s in re.split(r"(?<=[.!?;:])\s+", p) if s)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current)
            current = current[-overlap:] if overlap else ""
        current = f"{current}\n{piece}".strip() if current else piece
        # une phrase seule plus longue que `size` : découpe brute
        while len(current) > size:
            chunks.append(current[:size])
            current = current[size - overlap:] if overlap else current[size:]
    if current:
        chunks.append(current)
    return chunks


def chunk_document(doc: Document, size: int = 800, overlap: int = 150) -> list[Chunk]:
    chunks = []
    for page in doc.pages:
        for i, text in enumerate(split_text(page.text, size, overlap)):
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-p{page.number}-c{i}",
                    text=text,
                    metadata={
                        "doc_id": doc.doc_id,
                        "source": doc.source,
                        "page": page.number,
                        "has_images": bool(page.images),
                    },
                )
            )
    return chunks
