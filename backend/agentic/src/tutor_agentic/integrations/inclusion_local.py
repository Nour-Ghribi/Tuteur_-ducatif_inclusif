"""Local inclusion capabilities (image description, colour adaptation).

Colour adaptation is the pure-NumPy daltonization in ``inclusion/daltonize.py``. Image description
calls a vision-capable model through an OpenAI-compatible API (e.g. LLaVA on Ollama, or any hosted
vision model); with no ``TUTOR_VISION_MODEL`` configured the adapter reports "not configured" and the
graph shows the image with a clearly marked placeholder instead of an invented description.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from pathlib import Path

from ..assets import AssetRegistry
from ..config import Settings
from ..errors import AdapterNotConfigured, AdapterRejected, AdapterUnavailable
from ..inclusion import adapt_image
from .base import ResilientAdapter
from .contracts import (
    ColorAdaptationRequest,
    ColorAdaptationResponse,
    ImageDescriptionRequest,
    ImageDescriptionResponse,
)

Describer = Callable[
    [Path, str | None, str], tuple[str, str | None]
]  # (path, language, detail) -> (alt, long)

_PROMPT = (
    "Tu décris une figure d'un cours pour une personne qui ne la voit pas. Réponds exactement en deux "
    "lignes : « ALT: » suivi d'une phrase de 25 mots maximum, puis « LONG: » suivi d'une description "
    "détaillée (200 mots maximum) : ce que montre la figure, les légendes lisibles, les relations. "
    "Ne décris que ce qui est visible ; si un détail est illisible, dis-le. Langue : {lang}."
)


def parse_description(text: str) -> tuple[str, str | None]:
    alt, long_text = text.strip(), None
    if "ALT:" in text:
        _, _, tail = text.partition("ALT:")
        alt_part, _, long_part = tail.partition("LONG:")
        alt, long_text = alt_part.strip(), long_part.strip() or None
    return alt[:300] or "image", (long_text[:2000] if long_text else None)


def make_vision_describer(settings: Settings) -> Describer | None:
    if not settings.vision_model:
        return None
    from openai import OpenAI

    client = OpenAI(
        base_url=settings.vision_base_url or None,
        api_key=settings.vision_api_key.get_secret_value() if settings.vision_api_key else "none",
        timeout=settings.genai_timeout_s,
        max_retries=1,
    )

    def describe(path: Path, language: str | None, detail: str) -> tuple[str, str | None]:
        data = base64.b64encode(path.read_bytes()).decode()
        response = client.chat.completions.create(
            model=settings.vision_model,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT.format(lang=language or "français")},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{data}"},
                        },
                    ],
                }
            ],
        )
        return parse_description(response.choices[0].message.content or "")

    return describe


class LocalInclusionAdapter(ResilientAdapter):
    service = "inclusion"

    def __init__(
        self, assets: AssetRegistry, adapted_dir: Path, describer: Describer | None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._assets = assets
        self._adapted_dir = adapted_dir
        self._describer = describer
        self._cache: dict[str, ImageDescriptionResponse] = {}

    def _asset(self, ref: str, operation: str):
        asset = self._assets.get(ref)
        if asset is None:
            raise AdapterRejected(self.service, operation, "unknown image")
        return asset

    async def describe_image(self, request: ImageDescriptionRequest) -> ImageDescriptionResponse:
        async def call() -> ImageDescriptionResponse:
            asset = self._asset(request.image_ref, "describe_image")
            if self._describer is None:
                raise AdapterNotConfigured(
                    self.service, "describe_image", "no vision model configured"
                )
            if (cached := self._cache.get(asset.asset_id)) is not None:
                return cached
            try:
                alt, long_text = await asyncio.to_thread(
                    self._describer, asset.path, request.language, request.detail
                )
            except Exception as exc:
                raise AdapterUnavailable(
                    self.service, "describe_image", type(exc).__name__
                ) from exc
            result = ImageDescriptionResponse(
                alt_text=alt, long_description=long_text, model_id="vision"
            )
            self._cache[asset.asset_id] = result
            return result

        return await self._invoke("describe_image", call)

    async def adapt_colors(self, request: ColorAdaptationRequest) -> ColorAdaptationResponse:
        async def call() -> ColorAdaptationResponse:
            asset = self._asset(request.image_ref, "adapt_colors")
            target = self._adapted_dir / f"{asset.asset_id}-{request.deficiency.value}.png"
            if not target.is_file():
                try:
                    await asyncio.to_thread(adapt_image, asset.path, target, request.deficiency)
                except Exception as exc:
                    raise AdapterUnavailable(
                        self.service, "adapt_colors", type(exc).__name__
                    ) from exc
            adapted = self._assets.register(target, variant=request.deficiency.value)
            return ColorAdaptationResponse(
                adapted_image_ref=adapted.asset_id, method="machado2009+error-shift"
            )

        return await self._invoke("adapt_colors", call)
