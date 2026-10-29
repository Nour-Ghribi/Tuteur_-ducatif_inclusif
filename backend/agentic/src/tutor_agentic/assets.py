"""Opaque asset ids for course images.

The browser never receives file paths: it gets an id and fetches ``GET /assets/{id}``. Only files
registered here (extracted by the RAG ingestion, or produced by the colour adaptation) can be served.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Asset:
    asset_id: str
    path: Path
    content_type: str = "image/png"


class AssetRegistry:
    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {}

    def register(self, path: Path, *, variant: str = "original") -> Asset:
        resolved = path.resolve()
        digest = hashlib.sha256(f"{resolved}|{variant}".encode()).hexdigest()[:24]
        asset = Asset(asset_id=f"img-{digest}", path=resolved)
        self._assets[asset.asset_id] = asset
        return asset

    def get(self, asset_id: str) -> Asset | None:
        asset = self._assets.get(asset_id)
        return asset if asset and asset.path.is_file() else None
