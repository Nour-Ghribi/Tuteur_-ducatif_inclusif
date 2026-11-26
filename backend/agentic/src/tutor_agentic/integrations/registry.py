"""Builds the adapter set from configuration: real service when a URL is set, mock otherwise."""

from __future__ import annotations

from dataclasses import dataclass, fields

from ..assets import AssetRegistry
from ..config import Settings
from ..telemetry import Telemetry
from . import mocks
from .base import HttpJsonClient, ResiliencePolicy
from .ports import (
    AnswerEvaluationPort,
    ContentGenerationPort,
    HttpAnswerEvaluationAdapter,
    HttpContentGenerationAdapter,
    HttpInclusionAdapter,
    HttpIntentClassifierAdapter,
    HttpLearningRecordsAdapter,
    HttpRecommendationAdapter,
    HttpRetrievalAdapter,
    InclusionPort,
    IntentClassifierPort,
    LearningRecordsPort,
    RecommendationPort,
    RetrievalPort,
    UnconfiguredInclusionAdapter,
)


class ConfigurationError(RuntimeError):
    pass


@dataclass
class AdapterSet:
    retrieval: RetrievalPort
    generation: ContentGenerationPort
    evaluation: AnswerEvaluationPort
    recommendation: RecommendationPort
    learning_records: LearningRecordsPort
    inclusion: InclusionPort
    intent_classifier: IntentClassifierPort | None = None
    assets: AssetRegistry | None = None

    def modes(self) -> dict[str, str]:
        """``{"rag": "mock", ...}`` — reported by readiness checks."""
        result = {}
        for f in fields(self):
            if f.name == "assets":
                continue
            adapter = getattr(self, f.name)
            if adapter is None:
                mode = "disabled"
            elif type(adapter).__module__ == mocks.__name__:
                mode = "mock"
            elif type(adapter).__module__.endswith(("tuteur_backend", "inclusion_local")):
                mode = "tuteur" if "tuteur" in type(adapter).__module__ else "local"
            elif isinstance(adapter, UnconfiguredInclusionAdapter):
                mode = "unconfigured"
            else:
                mode = "http"
            result[f.name] = mode
        return result

    async def aclose(self) -> None:
        for f in fields(self):
            adapter = getattr(self, f.name)
            if f.name != "assets" and adapter is not None and hasattr(adapter, "aclose"):
                await adapter.aclose()


def _tuteur_adapters(settings: Settings, common: dict, tutor, assets: AssetRegistry) -> dict:
    """GenAI + RAG module used in-process: one shared Tutor, adapters sized for LLM latency."""
    from .base import ResiliencePolicy
    from .inclusion_local import LocalInclusionAdapter, make_vision_describer
    from .tuteur_backend import (
        TuteurAnswerEvaluationAdapter,
        TuteurGenerationAdapter,
        TuteurIntentClassifierAdapter,
        TuteurRetrievalAdapter,
    )

    llm_common = {
        "policy": ResiliencePolicy(
            timeout_s=settings.genai_timeout_s, max_retries=1, backoff_s=settings.adapter_backoff_s
        ),
        "telemetry": common["telemetry"],
    }
    return {
        "retrieval": TuteurRetrievalAdapter(tutor, assets, settings.images_dir, **common),
        "generation": TuteurGenerationAdapter(tutor, **llm_common),
        "evaluation": TuteurAnswerEvaluationAdapter(tutor, **llm_common),
        "intent_classifier": TuteurIntentClassifierAdapter(tutor, **llm_common)
        if settings.intent_classifier_enabled
        else None,
        "inclusion": LocalInclusionAdapter(
            assets, settings.adapted_images_dir, make_vision_describer(settings), **llm_common
        ),
    }


def build_adapters(settings: Settings, telemetry: Telemetry, tutor=None) -> AdapterSet:
    """``tutor``: an existing GenAI-module ``Tutor`` (tests/dev); built on demand when backend=tuteur."""
    policy = ResiliencePolicy(
        timeout_s=settings.adapter_timeout_s,
        max_retries=settings.adapter_max_retries,
        backoff_s=settings.adapter_backoff_s,
    )
    common = {"policy": policy, "telemetry": telemetry}
    api_key = settings.service_api_key.get_secret_value() if settings.service_api_key else None
    assets = AssetRegistry()

    def http(service: str, url) -> HttpJsonClient:
        return HttpJsonClient(service, str(url), timeout_s=policy.timeout_s, api_key=api_key)

    def pick(name: str, url, http_cls, mock_cls, *, required: bool = True):
        if url:
            return http_cls(http=http(http_cls.service, url), **common)
        if settings.allow_mocks:
            return mock_cls(**common)
        if required:
            raise ConfigurationError(f"{name} service URL is required when mocks are disabled")
        return None

    genai_url = settings.genai_service_url
    classifier = None
    if settings.intent_classifier_enabled:
        classifier = pick(
            "intent classifier",
            genai_url,
            HttpIntentClassifierAdapter,
            mocks.MockIntentClassifierAdapter,
            required=False,
        )
    parts = {
        "retrieval": pick(
            "RAG", settings.rag_service_url, HttpRetrievalAdapter, mocks.MockRetrievalAdapter
        ),
        "generation": pick(
            "GenAI", genai_url, HttpContentGenerationAdapter, mocks.MockContentGenerationAdapter
        ),
        "evaluation": pick(
            "GenAI", genai_url, HttpAnswerEvaluationAdapter, mocks.MockAnswerEvaluationAdapter
        ),
        "inclusion": pick(
            "inclusion",
            settings.inclusion_service_url,
            HttpInclusionAdapter,
            mocks.MockInclusionAdapter,
            required=False,
        )
        or UnconfiguredInclusionAdapter(),
        "intent_classifier": classifier,
    }
    if settings.genai_backend == "tuteur":
        from .tuteur_backend import build_tutor

        parts.update(_tuteur_adapters(settings, common, tutor or build_tutor(settings), assets))
    elif tutor is not None:
        raise ConfigurationError("a Tutor instance is only used with TUTOR_GENAI_BACKEND=tuteur")

    return AdapterSet(
        recommendation=pick(
            "RL",
            settings.rl_service_url,
            HttpRecommendationAdapter,
            mocks.MockRecommendationAdapter,
        ),
        learning_records=pick(
            "learning records",
            settings.learning_records_service_url,
            HttpLearningRecordsAdapter,
            mocks.MockLearningRecordsAdapter,
        ),
        assets=assets,
        **parts,
    )
