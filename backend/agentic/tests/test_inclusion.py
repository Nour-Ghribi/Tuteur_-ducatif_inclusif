import numpy as np
import pytest
from PIL import Image

from tutor_agentic.assets import AssetRegistry
from tutor_agentic.errors import AdapterNotConfigured, AdapterRejected
from tutor_agentic.inclusion import adapt_image, adapt_pixels
from tutor_agentic.integrations.contracts import (
    ColorAdaptationRequest,
    ImageDescriptionRequest,
    ImageDescriptionResponse,
    RetrievalResponse,
)
from tutor_agentic.integrations.inclusion_local import LocalInclusionAdapter, parse_description
from tutor_agentic.integrations.mocks import (
    FaultInjector,
    MockInclusionAdapter,
    MockRetrievalAdapter,
)
from tutor_agentic.schemas.common import AccessibilityPreferences, ColorVisionDeficiency
from tutor_agentic.schemas.requests import ExperienceRequest

CVD = [c for c in ColorVisionDeficiency if c is not ColorVisionDeficiency.NONE]


class TestDaltonize:
    @pytest.mark.parametrize("deficiency", CVD)
    def test_greys_are_unchanged(self, deficiency):
        grey = np.linspace(0, 1, 11)[:, None].repeat(3, axis=1)
        assert np.allclose(adapt_pixels(grey, deficiency), grey, atol=1e-3)

    @pytest.mark.parametrize(
        "deficiency", [ColorVisionDeficiency.PROTANOPIA, ColorVisionDeficiency.DEUTERANOPIA]
    )
    def test_red_green_confusion_is_changed(self, deficiency):
        red_green = np.array([[0.8, 0.2, 0.1], [0.2, 0.7, 0.1]])
        adapted = adapt_pixels(red_green, deficiency)
        assert not np.allclose(adapted, red_green, atol=0.02)
        assert adapted.min() >= 0 and adapted.max() <= 1

    def test_requires_a_declared_deficiency(self):
        with pytest.raises(ValueError):
            adapt_pixels(np.zeros((1, 3)), ColorVisionDeficiency.NONE)

    def test_image_round_trip_keeps_size_and_alpha(self, tmp_path):
        source = tmp_path / "in.png"
        Image.new("RGBA", (8, 6), (200, 40, 30, 128)).save(source)
        target = adapt_image(source, tmp_path / "out" / "o.png", ColorVisionDeficiency.PROTANOPIA)
        with Image.open(target) as out:
            assert out.size == (8, 6) and out.mode == "RGBA"
            assert out.getpixel((0, 0))[3] == 128
            assert out.getpixel((0, 0))[:3] != (200, 40, 30)


class TestParsing:
    def test_two_line_format(self):
        alt, long_text = parse_description(
            "ALT: Un schéma de la feuille.\nLONG: Détails de la feuille."
        )
        assert alt == "Un schéma de la feuille." and long_text == "Détails de la feuille."

    def test_free_text_falls_back_to_alt_only(self):
        alt, long_text = parse_description("Une figure.")
        assert alt == "Une figure." and long_text is None


@pytest.fixture
def local_adapter(adapter_kwargs, tmp_path):
    source = tmp_path / "fig.png"
    Image.new("RGB", (10, 10), (210, 30, 30)).save(source)
    assets = AssetRegistry()
    ref = assets.register(source).asset_id
    calls = []

    def describer(path, language, detail):
        calls.append((path.name, language, detail))
        return "Schéma de feuille", "Longue description"

    adapter = LocalInclusionAdapter(assets, tmp_path / "adapted", describer, **adapter_kwargs)
    return adapter, assets, ref, calls


class TestLocalInclusionAdapter:
    async def test_description_is_cached_per_image(self, local_adapter):
        adapter, _, ref, calls = local_adapter
        first = await adapter.describe_image(ImageDescriptionRequest(image_ref=ref))
        await adapter.describe_image(ImageDescriptionRequest(image_ref=ref))
        assert first.alt_text == "Schéma de feuille" and first.simulated is False
        assert len(calls) == 1

    async def test_unknown_image_is_rejected(self, local_adapter):
        adapter, *_ = local_adapter
        with pytest.raises(AdapterRejected):
            await adapter.describe_image(ImageDescriptionRequest(image_ref="img-unknown"))

    async def test_no_vision_model_means_not_configured(self, adapter_kwargs, tmp_path):
        assets = AssetRegistry()
        (tmp_path / "a.png").write_bytes(b"x")
        ref = assets.register(tmp_path / "a.png").asset_id
        with pytest.raises(AdapterNotConfigured):
            await LocalInclusionAdapter(assets, tmp_path, None, **adapter_kwargs).describe_image(
                ImageDescriptionRequest(image_ref=ref)
            )

    async def test_adapted_variant_is_a_new_registered_asset(self, local_adapter):
        adapter, assets, ref, _ = local_adapter
        request = ColorAdaptationRequest(
            image_ref=ref, deficiency=ColorVisionDeficiency.DEUTERANOPIA
        )
        result = await adapter.adapt_colors(request)
        again = await adapter.adapt_colors(request)
        assert result.adapted_image_ref != ref == assets.get(ref).asset_id
        assert result.adapted_image_ref == again.adapted_image_ref
        assert assets.get(result.adapted_image_ref).path.is_file()


class ImageRetrieval(MockRetrievalAdapter):
    """Mock RAG whose chunks carry image references (as the real ingestion provides)."""

    async def retrieve(self, request):
        response = await super().retrieve(request)
        for chunk in response.chunks[:1]:
            chunk.image_refs = ["img-aaa", "img-bbb", "img-ccc"]
        return RetrievalResponse(**response.model_dump())


class RichInclusion(MockInclusionAdapter):
    async def describe_image(self, request):
        return ImageDescriptionResponse(
            alt_text="Schéma", long_description="Description longue", simulated=True
        )


def explain(**prefs):
    return ExperienceRequest(
        message="Explain",
        course_id="demo-bio-101",
        topic="photosynthèse",
        preferences=AccessibilityPreferences(**prefs),
    )


async def run(make_service, student, adapter_kwargs, request, **overrides):
    service = make_service(retrieval=ImageRetrieval(**adapter_kwargs), **overrides)
    return await service.create_experience(student, request)


class TestImagesInWorkflow:
    async def test_figures_follow_the_title_with_alt_text(
        self, make_service, student, adapter_kwargs
    ):
        response = await run(make_service, student, adapter_kwargs, explain())
        types = [b.type for b in response.ui.blocks]
        assert types[:3] == ["heading", "image", "image"]  # capped at two figures
        image = response.ui.blocks[1]
        assert image.alt_text and not image.adapted and image.long_description is None
        assert "inclusion" in response.ui.meta.simulated_services

    async def test_screen_reader_preference_adds_long_description(
        self, make_service, student, adapter_kwargs
    ):
        response = await run(
            make_service,
            student,
            adapter_kwargs,
            explain(screen_reader_optimized=True),
            inclusion=RichInclusion(**adapter_kwargs),
        )
        assert response.ui.blocks[1].long_description == "Description longue"

    async def test_declared_colour_vision_requests_the_adapted_variant(
        self, make_service, student, adapter_kwargs
    ):
        response = await run(
            make_service,
            student,
            adapter_kwargs,
            explain(color_vision=ColorVisionDeficiency.DEUTERANOPIA),
        )
        assert response.ui.blocks[1].adapted is True

    async def test_no_colour_declared_means_no_adaptation(
        self, make_service, student, adapter_kwargs
    ):
        inclusion = MockInclusionAdapter(**adapter_kwargs)
        await run(make_service, student, adapter_kwargs, explain(), inclusion=inclusion)
        assert inclusion.calls == 2  # two descriptions, zero adaptations: nothing is inferred

    async def test_adaptation_failure_keeps_original_with_warning(
        self, make_service, student, adapter_kwargs
    ):
        inclusion = MockInclusionAdapter(faults=FaultInjector("unavailable"), **adapter_kwargs)
        response = await run(
            make_service,
            student,
            adapter_kwargs,
            explain(color_vision=ColorVisionDeficiency.PROTANOPIA),
            inclusion=inclusion,
        )
        warnings = response.ui.meta.warnings
        assert "color_adaptation_failed" in warnings and "image_description_unavailable" in warnings
        image = response.ui.blocks[1]
        assert (
            image.description_source == "placeholder"
            and image.alt_text is None
            and not image.adapted
        )

    async def test_reduced_visual_complexity_skips_figures(
        self, make_service, student, adapter_kwargs
    ):
        response = await run(
            make_service, student, adapter_kwargs, explain(reduced_visual_complexity=True)
        )
        assert "image" not in [b.type for b in response.ui.blocks]
