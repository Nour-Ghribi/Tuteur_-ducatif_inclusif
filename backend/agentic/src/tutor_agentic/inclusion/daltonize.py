"""Colour adaptation for declared colour-vision deficiencies.

Method: simulate the deficiency with the Machado et al. (2009) matrices (severity 1.0, linear RGB),
take the colour information the viewer loses (original - simulated) and shift it into channels they
can still distinguish (the classic "daltonize" error-shift). Greys are left unchanged because every
simulation matrix row sums to 1. This is a lightweight heuristic, not a medical device.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..schemas.common import ColorVisionDeficiency

_SIMULATE = {
    ColorVisionDeficiency.PROTANOPIA: np.array(
        [
            [0.152286, 1.052583, -0.204868],
            [0.114503, 0.786281, 0.099216],
            [-0.003882, -0.048116, 1.051998],
        ]
    ),
    ColorVisionDeficiency.DEUTERANOPIA: np.array(
        [
            [0.367322, 0.860646, -0.227968],
            [0.280085, 0.672501, 0.047413],
            [-0.011820, 0.042940, 0.968881],
        ]
    ),
    ColorVisionDeficiency.TRITANOPIA: np.array(
        [
            [1.255528, -0.076749, -0.178779],
            [-0.078411, 0.930809, 0.147602],
            [0.004733, 0.691367, 0.303900],
        ]
    ),
}
_SHIFT = {
    ColorVisionDeficiency.PROTANOPIA: np.array([[0.0, 0, 0], [0.7, 1, 0], [0.7, 0, 1]]),
    ColorVisionDeficiency.DEUTERANOPIA: np.array([[0.0, 0, 0], [0.7, 1, 0], [0.7, 0, 1]]),
    ColorVisionDeficiency.TRITANOPIA: np.array([[1.0, 0, 0.7], [0, 1, 0.7], [0, 0, 0]]),
}


def _to_linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def adapt_pixels(rgb: np.ndarray, deficiency: ColorVisionDeficiency) -> np.ndarray:
    """``rgb``: float array (..., 3) in [0, 1] (sRGB). Returns the adapted array, same shape."""
    if deficiency is ColorVisionDeficiency.NONE:
        raise ValueError("a declared colour vision deficiency is required")
    linear = _to_linear(rgb)
    simulated = linear @ _SIMULATE[deficiency].T
    shifted = (linear - simulated) @ _SHIFT[deficiency].T
    return _to_srgb(linear + shifted)


def adapt_image(source: Path, target: Path, deficiency: ColorVisionDeficiency) -> Path:
    with Image.open(source) as image:
        has_alpha = "A" in image.getbands()
        rgba = image.convert("RGBA")
    data = np.asarray(rgba, dtype=np.float64) / 255.0
    adapted = adapt_pixels(data[..., :3], deficiency)
    out = np.concatenate([adapted, data[..., 3:]], axis=-1) if has_alpha else adapted
    mode = "RGBA" if has_alpha else "RGB"
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(out, 0, 1) * 255).round().astype(np.uint8), mode).save(
        target, format="PNG"
    )
    return target
