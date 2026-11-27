"""Tests for the VLM image description module (src/tuteur/vision.py).

All tests are offline — no VLM calls are made.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tuteur.vision import VLMDescriber, _parse_response, describe_page_images


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_well_formed():
    text = "ALT: Un diagramme montrant la photosynthèse.\nLONG: La figure montre..."
    alt, long_desc = _parse_response(text)
    assert alt.startswith("Un diagramme")
    assert long_desc.startswith("La figure")


def test_parse_response_no_markers():
    text = "Juste une description simple."
    alt, long_desc = _parse_response(text)
    assert alt == "Juste une description simple."
    assert long_desc == ""


def test_parse_response_truncates_alt():
    text = "ALT: " + "a" * 500 + "\nLONG: détail"
    alt, _ = _parse_response(text)
    assert len(alt) <= 300


def test_parse_response_truncates_long():
    text = "ALT: court\nLONG: " + "b" * 3000
    _, long_desc = _parse_response(text)
    assert len(long_desc) <= 2000


# ---------------------------------------------------------------------------
# describe_page_images — sidecar caching (no VLM)
# ---------------------------------------------------------------------------

class _FakeDescriber:
    def __init__(self):
        self.calls = 0

    def describe(self, path: Path) -> tuple[str, str]:
        self.calls += 1
        return "ALT: Image test.", "LONG: Description détaillée."


def test_describe_uses_sidecar_when_exists(tmp_path):
    img = tmp_path / "p1_img0.png"
    img.write_bytes(b"fake")
    sidecar = img.with_suffix(".txt")
    sidecar.write_text("ALT: Depuis sidecar.\nLONG: Détail.", encoding="utf-8")

    describer = _FakeDescriber()
    results = describe_page_images([img], describer)
    assert len(results) == 1
    assert results[0][1] == "Depuis sidecar."
    assert describer.calls == 0   # sidecar used, no VLM call


def test_describe_calls_vlm_when_no_sidecar(tmp_path):
    img = tmp_path / "p1_img0.png"
    img.write_bytes(b"fake")

    describer = _FakeDescriber()
    results = describe_page_images([img], describer)
    assert len(results) == 1
    assert describer.calls == 1
    # Sidecar should now exist
    assert img.with_suffix(".txt").exists()


def test_describe_force_redescribes(tmp_path):
    img = tmp_path / "p1_img0.png"
    img.write_bytes(b"fake")
    sidecar = img.with_suffix(".txt")
    sidecar.write_text("ALT: Ancien.\nLONG: .", encoding="utf-8")

    describer = _FakeDescriber()
    results = describe_page_images([img], describer, force=True)
    assert describer.calls == 1
    assert results[0][1] == "ALT: Image test."


def test_describe_skips_failed_images(tmp_path):
    img = tmp_path / "p1_img0.png"
    img.write_bytes(b"fake")

    class _FailingDescriber:
        def describe(self, path):
            raise RuntimeError("VLM unavailable")

    results = describe_page_images([img], _FailingDescriber())
    assert results == []   # graceful skip


def test_describe_multiple_images(tmp_path):
    imgs = []
    for j in range(3):
        img = tmp_path / f"p1_img{j}.png"
        img.write_bytes(b"fake")
        imgs.append(img)

    describer = _FakeDescriber()
    results = describe_page_images(imgs, describer)
    assert len(results) == 3
    assert describer.calls == 3
