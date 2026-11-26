"""Extraction du texte et des images d'un support de cours (PDF, TXT, MD)."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz


@dataclass
class Page:
    number: int  # 1-indexé
    text: str
    images: list[Path] = field(default_factory=list)


@dataclass
class Document:
    doc_id: str
    source: str
    pages: list[Page]


def _doc_id(path: Path) -> str:
    # Identifiant stable basé sur le contenu : ré-ingérer le même fichier ne crée pas de doublons.
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def load_pdf(path: Path, images_dir: Path | None = None, min_image_px: int = 100) -> Document:
    doc_id = _doc_id(path)
    pages = []
    with fitz.open(path) as pdf:
        for i, pdf_page in enumerate(pdf, start=1):
            page = Page(number=i, text=pdf_page.get_text("text").strip())
            if images_dir is not None:
                page.images = _extract_images(pdf, pdf_page, images_dir / doc_id, i, min_image_px)
            pages.append(page)
    return Document(doc_id=doc_id, source=path.name, pages=pages)


def _extract_images(pdf, pdf_page, out_dir: Path, page_no: int, min_px: int) -> list[Path]:
    saved = []
    for j, img in enumerate(pdf_page.get_images(full=True)):
        pix = fitz.Pixmap(pdf, img[0])
        if pix.width < min_px or pix.height < min_px:
            continue  # ignore icônes et puces
        if pix.n - pix.alpha >= 4:  # CMYK -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"p{page_no}_img{j}.png"
        pix.save(out)
        saved.append(out)
    return saved


def load_text(path: Path) -> Document:
    return Document(
        doc_id=_doc_id(path),
        source=path.name,
        pages=[Page(number=1, text=path.read_text(encoding="utf-8").strip())],
    )


def load_document(path: Path, images_dir: Path | None = None) -> Document:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path, images_dir)
    if suffix in {".txt", ".md"}:
        return load_text(path)
    raise ValueError(f"Format non supporté : {suffix}")
