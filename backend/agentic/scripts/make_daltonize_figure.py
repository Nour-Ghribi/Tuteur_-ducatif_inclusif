"""Builds the before/after figure of the colour adaptation (used by the report).

    python scripts/make_daltonize_figure.py ../../docs/agentic/img

Writes three PNGs from one synthetic chart: the original, what a person with deuteranopia sees
(Machado et al. 2009 simulation), and the adapted image produced by ``adapt_image``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tutor_agentic.inclusion.daltonize import _SIMULATE, _to_linear, _to_srgb, adapt_image
from tutor_agentic.schemas.common import ColorVisionDeficiency

DEFICIENCY = ColorVisionDeficiency.DEUTERANOPIA
BARS = [(200, 60, 45), (70, 165, 75), (225, 140, 30), (50, 110, 190)]  # red, green, orange, blue


def synthetic_chart(path: Path) -> None:
    image = Image.new("RGB", (320, 140), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for i, color in enumerate(BARS):
        left = 20 + i * 75
        draw.rectangle([left, 125 - (50 + i * 15), left + 55, 125], fill=color)
    image.save(path)


def simulate(source: Path, target: Path) -> None:
    rgb = np.asarray(Image.open(source).convert("RGB"), dtype=np.float64) / 255.0
    simulated = _to_srgb(_to_linear(rgb) @ _SIMULATE[DEFICIENCY].T)
    Image.fromarray((simulated * 255).round().astype(np.uint8)).save(target)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    original = out / "daltonize-1-original.png"
    synthetic_chart(original)
    simulate(original, out / "daltonize-2-simule.png")
    adapted = out / "_adapted.png"
    adapt_image(original, adapted, DEFICIENCY)
    simulate(
        adapted, out / "daltonize-3-adapte-vu.png"
    )  # what the same person sees after adaptation
    adapted.replace(out / "daltonize-4-adapte.png")
    print("written to", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("daltonize"))
