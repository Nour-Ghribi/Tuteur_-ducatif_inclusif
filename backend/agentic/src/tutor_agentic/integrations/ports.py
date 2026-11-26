"""Adapter interfaces (ports) and their HTTP implementations.

Graph nodes depend only on the Protocols. Replacing a mock with a teammate's real service is a
configuration change (set the service URL), not a code change.
"""

from __future__ import annotations

from typing import Protocol

from ..errors import AdapterNotConfigured
from .base import HttpJsonClient, ResilientAdapter
from .contracts import (
    AnswerEvaluationRequest,
    AnswerEvaluationResponse,
    ColorAdaptationRequest,
    ColorAdaptationResponse,
    GenerationRequest,
    GenerationResponse,
    ImageDescriptionRequest,
    ImageDescriptionResponse,
    IntentClassificationRequest,
    IntentClassificationResponse,
    LearningSummariesRequest,
    LearningSummariesResponse,
    OutcomeAckResponse,
    OutcomeReport,
    RecommendationServiceRequest,
    RecommendationServiceResponse,
    RetrievalRequest,
    RetrievalResponse,
)


class RetrievalPort(Protocol):
    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse: ...


class ContentGenerationPort(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...


class AnswerEvaluationPort(Protocol):
    async def evaluate(self, request: AnswerEvaluationRequest) -> AnswerEvaluationResponse: ...


class IntentClassifierPort(Protocol):
    async def classify(
        self, request: IntentClassificationRequest
    ) -> IntentClassificationResponse: ...


class InclusionPort(Protocol):
    async def describe_image(
        self, request: ImageDescriptionRequest
    ) -> ImageDescriptionResponse: ...

    async def adapt_colors(self, request: ColorAdaptationRequest) -> ColorAdaptationResponse: ...


class RecommendationPort(Protocol):
    async def recommend(
        self, request: RecommendationServiceRequest
    ) -> RecommendationServiceResponse: ...

    async def report_outcome(self, request: OutcomeReport) -> OutcomeAckResponse: ...


class LearningRecordsPort(Protocol):
    async def summaries(self, request: LearningSummariesRequest) -> LearningSummariesResponse: ...


class _HttpAdapter(ResilientAdapter):
    def __init__(self, http: HttpJsonClient, **kwargs) -> None:
        super().__init__(**kwargs)
        self._http = http

    async def aclose(self) -> None:
        await self._http.aclose()


class HttpRetrievalAdapter(_HttpAdapter):
    service = "rag"

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        return await self._invoke(
            "retrieve",
            lambda: self._http.request(
                "POST", "retrieve", "/v1/retrieve", RetrievalResponse, payload=request
            ),
        )


class HttpContentGenerationAdapter(_HttpAdapter):
    service = "genai"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return await self._invoke(
            "generate",
            lambda: self._http.request(
                "POST", "generate", "/v1/generate", GenerationResponse, payload=request
            ),
        )


class HttpAnswerEvaluationAdapter(_HttpAdapter):
    service = "genai"

    async def evaluate(self, request: AnswerEvaluationRequest) -> AnswerEvaluationResponse:
        return await self._invoke(
            "evaluate_answer",
            lambda: self._http.request(
                "POST",
                "evaluate_answer",
                "/v1/evaluate-answer",
                AnswerEvaluationResponse,
                payload=request,
            ),
        )


class HttpIntentClassifierAdapter(_HttpAdapter):
    service = "genai"

    async def classify(self, request: IntentClassificationRequest) -> IntentClassificationResponse:
        return await self._invoke(
            "classify_intent",
            lambda: self._http.request(
                "POST",
                "classify_intent",
                "/v1/classify-intent",
                IntentClassificationResponse,
                payload=request,
            ),
        )


class HttpInclusionAdapter(_HttpAdapter):
    service = "inclusion"

    async def describe_image(self, request: ImageDescriptionRequest) -> ImageDescriptionResponse:
        return await self._invoke(
            "describe_image",
            lambda: self._http.request(
                "POST",
                "describe_image",
                "/v1/describe-image",
                ImageDescriptionResponse,
                payload=request,
            ),
        )

    async def adapt_colors(self, request: ColorAdaptationRequest) -> ColorAdaptationResponse:
        return await self._invoke(
            "adapt_colors",
            lambda: self._http.request(
                "POST", "adapt_colors", "/v1/adapt-colors", ColorAdaptationResponse, payload=request
            ),
        )


class HttpRecommendationAdapter(_HttpAdapter):
    service = "rl"

    async def recommend(
        self, request: RecommendationServiceRequest
    ) -> RecommendationServiceResponse:
        return await self._invoke(
            "recommend",
            lambda: self._http.request(
                "POST", "recommend", "/v1/recommend", RecommendationServiceResponse, payload=request
            ),
        )

    async def report_outcome(self, request: OutcomeReport) -> OutcomeAckResponse:
        return await self._invoke(
            "report_outcome",
            lambda: self._http.request(
                "POST", "report_outcome", "/v1/outcomes", OutcomeAckResponse, payload=request
            ),
        )


class HttpLearningRecordsAdapter(_HttpAdapter):
    service = "learning_records"

    async def summaries(self, request: LearningSummariesRequest) -> LearningSummariesResponse:
        return await self._invoke(
            "summaries",
            lambda: self._http.request(
                "POST",
                "summaries",
                "/v1/learning-summaries",
                LearningSummariesResponse,
                payload=request,
            ),
        )


class UnconfiguredInclusionAdapter:
    """Used when no inclusion service exists and mocks are not allowed."""

    service = "inclusion"

    async def describe_image(self, request: ImageDescriptionRequest) -> ImageDescriptionResponse:
        raise AdapterNotConfigured(self.service, "describe_image", "no inclusion service URL")

    async def adapt_colors(self, request: ColorAdaptationRequest) -> ColorAdaptationResponse:
        raise AdapterNotConfigured(self.service, "adapt_colors", "no inclusion service URL")

    async def aclose(self) -> None:
        return None
