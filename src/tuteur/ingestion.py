"""Extraction du texte et des images d'un support de cours (PDF, TXT, MD).

Step 6 addition: optional VLM image description at ingestion time.
Pass a VLMDescriber to load_pdf() / load_document() to have each extracted
image described immediately. The descriptions are written as .txt sidecars
next to the PNGs so that:
  - chunk_document() picks them up without needing the VLM again.
  - Re-ingesting the same file skips already-described images.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

log = logging.getLogger(__name__)


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


def load_pdf(
    path: Path,
    images_dir: Path | None = None,
    min_image_px: int = 100,
    describer=None,          # VLMDescriber | None
    force_redescribe: bool = False,
) -> Document:
    """Load a PDF, extract text and images, optionally describe images with VLM.

    Parameters
    ----------
    path : Path
        PDF file to load.
    images_dir : Path | None
        Directory where extracted PNGs are saved. None = skip image extraction.
    min_image_px : int
        Minimum image dimension (width or height) in pixels to keep.
        Smaller images (icons, bullets) are ignored.
    describer : VLMDescriber | None
        If provided, each extracted PNG is described immediately.
        Results are cached as .txt sidecars — subsequent calls are free.
    force_redescribe : bool
        If True, re-describe images even if a sidecar already exists.
    """
    doc_id = _doc_id(path)
    pages = []
    with fitz.open(path) as pdf:
        for i, pdf_page in enumerate(pdf, start=1):
            page = Page(number=i, text=pdf_page.get_text("text").strip())
            if images_dir is not None:
                page.images = _extract_images(
                    pdf, pdf_page, images_dir / doc_id, i, min_image_px
                )
                # --- VLM description (Step 6) ---
                if describer is not None and page.images:
                    _describe_images(page.images, describer, force=force_redescribe)
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


def _describe_images(image_paths: list[Path], describer, force: bool = False) -> None:
    """Call describer on each image that has no sidecar yet (or if force=True)."""
    from tuteur.vision import describe_page_images
    described = describe_page_images(image_paths, describer, force=force)
    log.debug("Described %d / %d images", len(described), len(image_paths))


def load_text(path: Path) -> Document:
    return Document(
        doc_id=_doc_id(path),
        source=path.name,
        pages=[Page(number=1, text=path.read_text(encoding="utf-8").strip())],
    )


def load_document(
    path: Path,
    images_dir: Path | None = None,
    describer=None,           # VLMDescriber | None
    force_redescribe: bool = False,
) -> Document:
    """Load a PDF, TXT or MD document.

    Parameters
    ----------
    path : Path
        File to load.
    images_dir : Path | None
        Directory for extracted images. None = skip image extraction.
    describer : VLMDescriber | None
        Optional VLM for image description (PDF only).
    force_redescribe : bool
        Re-describe images even if sidecar files exist.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(
            path,
            images_dir=images_dir,
            describer=describer,
            force_redescribe=force_redescribe,
        )
    if suffix in {".txt", ".md"}:
        return load_text(path)
    raise ValueError(f"Format non supporté : {suffix}")
