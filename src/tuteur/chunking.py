"""Découpage du texte en passages (chunks) avec chevauchement, page par page.

Step 6 addition: image description chunks.
When a page has images that have been described by the VLM (sidecar .txt files),
an extra chunk of type "image_caption" is produced for each image. This chunk
is embedded and stored in ChromaDB alongside the text chunks so that queries
about diagram content retrieve the relevant image description.

Chunk id convention:
  text   : {doc_id}-p{page}-c{i}
  image  : {doc_id}-p{page}-img{j}
"""

import re
from dataclasses import dataclass
from pathlib import Path

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


def _image_description_chunks(
    doc_id: str,
    source: str,
    page_number: int,
    image_paths: list[Path],
) -> list[Chunk]:
    """Produce one chunk per image that has a sidecar .txt description.

    The chunk text is the full description (alt + long). It carries
    ``type: "image_caption"`` in metadata so the generation layer knows
    this chunk came from a figure, not running text.

    Images without a sidecar are silently skipped — the page still gets
    ``has_images: True`` on its text chunks.
    """
    chunks: list[Chunk] = []
    for j, img_path in enumerate(image_paths):
        sidecar = img_path.with_suffix(".txt")
        if not sidecar.exists():
            continue
        raw = sidecar.read_text(encoding="utf-8").strip()
        if not raw:
            continue
        # Combine alt + long into one searchable text block
        # (the RAG system embeds the whole thing; the UI shows only alt as caption)
        chunks.append(
            Chunk(
                id=f"{doc_id}-p{page_number}-img{j}",
                text=raw[:4000],  # ChromaDB document limit
                metadata={
                    "doc_id": doc_id,
                    "source": source,
                    "page": page_number,
                    "type": "image_caption",
                    "image_path": str(img_path),
                    "has_images": True,
                },
            )
        )
    return chunks


def chunk_document(
    doc: Document,
    size: int = 800,
    overlap: int = 150,
    include_image_descriptions: bool = True,
) -> list[Chunk]:
    """Produce text chunks (and optionally image-description chunks) for a Document.

    Parameters
    ----------
    doc : Document
        Loaded document with pages and optional image paths.
    size : int
        Maximum characters per text chunk.
    overlap : int
        Characters of overlap between consecutive text chunks.
    include_image_descriptions : bool
        If True (default), add image_caption chunks for every page image that
        has a VLM sidecar (.txt file). Set to False to skip image chunks.
    """
    chunks: list[Chunk] = []
    for page in doc.pages:
        # --- text chunks ---
        for i, text in enumerate(split_text(page.text, size, overlap)):
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-p{page.number}-c{i}",
                    text=text,
                    metadata={
                        "doc_id": doc.doc_id,
                        "source": doc.source,
                        "page": page.number,
                        "type": "text",
                        "has_images": bool(page.images),
                    },
                )
            )
        # --- image description chunks (Step 6) ---
        if include_image_descriptions and page.images:
            chunks.extend(
                _image_description_chunks(
                    doc.doc_id, doc.source, page.number, page.images
                )
            )
    return chunks
