import time

import httpx
import pytest
import respx

from tutor_agentic.config import Settings
from tutor_agentic.errors import (
    AdapterRejected,
    AdapterTimeout,
    AdapterUnavailable,
    MalformedResponse,
)
from tutor_agentic.integrations import ConfigurationError, build_adapters
from tutor_agentic.integrations.base import HttpJsonClient
from tutor_agentic.integrations.contracts import (
    ActivityOption,
    LearnerFeatures,
    LearningSummariesRequest,
    RecommendationServiceRequest,
    RetrievalRequest,
)
from tutor_agentic.integrations.mocks import (
    FaultInjector,
    MockLearningRecordsAdapter,
    MockRecommendationAdapter,
    MockRetrievalAdapter,
)
from tutor_agentic.integrations.ports import HttpRetrievalAdapter
from tutor_agentic.schemas.common import ActivityType, Difficulty
from tutor_agentic.telemetry import ADAPTER_CALL, request_id_var

RAG_URL = "http://rag.test"
QUERY = RetrievalRequest(query="photosynthèse chlorophylle", course_id="demo-bio-101")


class TestMocks:
    async def test_rag_mock_is_labelled_and_grounded_in_synthetic_corpus(self, adapter_kwargs):
        response = await MockRetrievalAdapter(**adapter_kwargs).retrieve(QUERY)
        assert response.simulated is True
        assert response.chunks and all(c.source.doc_id for c in response.chunks)

    async def test_rag_mock_unknown_course_returns_nothing(self, adapter_kwargs):
        request = RetrievalRequest(query="x", course_id="unknown")
        assert (await MockRetrievalAdapter(**adapter_kwargs).retrieve(request)).chunks == []

    async def test_rl_mock_only_recommends_offered_activities(self, adapter_kwargs):
        offered = [
            ActivityOption(activity_type=ActivityType.QUIZ, difficulty=Difficulty.HARD, topic="t")
        ]
        response = await MockRecommendationAdapter(**adapter_kwargs).recommend(
            RecommendationServiceRequest(
                student_ref="s1",
                course_id="c",
                topic="t",
                features=LearnerFeatures(last_outcome="incorrect"),
                available_activities=offered,
            )
        )
        assert (response.activity_type, response.difficulty) == (ActivityType.QUIZ, Difficulty.HARD)
        assert response.simulated is True

    async def test_learning_records_mock_is_aggregate_and_simulated(self, adapter_kwargs):
        from datetime import date

        data = await MockLearningRecordsAdapter(**adapter_kwargs).summaries(
            LearningSummariesRequest(
                class_id="class-demo-a", period_start=date(2026, 9, 1), period_end=date(2026, 10, 1)
            )
        )
        assert data.simulated is True
        assert not hasattr(data, "learners")


class TestResilience:
    async def test_transient_failure_is_retried_then_succeeds(self, adapter_kwargs, sink):
        faults = FaultInjector("unavailable", times=2)
        adapter = MockRetrievalAdapter(faults=faults, **adapter_kwargs)
        response = await adapter.retrieve(QUERY)
        assert response.chunks
        assert faults.calls == 3
        event = sink.named(ADAPTER_CALL)[-1]
        assert event.attributes["outcome"] == "success"
        assert event.attributes["attempts"] == 3

    async def test_retries_are_bounded(self, adapter_kwargs, sink):
        faults = FaultInjector("unavailable")
        with pytest.raises(AdapterUnavailable):
            await MockRetrievalAdapter(faults=faults, **adapter_kwargs).retrieve(QUERY)
        assert faults.calls == 3  # 1 attempt + max_retries=2
        assert sink.named(ADAPTER_CALL)[-1].attributes["error_code"] == "adapter_unavailable"

    async def test_timeout_is_enforced(self, adapter_kwargs):
        started = time.perf_counter()
        with pytest.raises(AdapterTimeout):
            await MockRetrievalAdapter(faults=FaultInjector("timeout"), **adapter_kwargs).retrieve(
                QUERY
            )
        assert time.perf_counter() - started < 2  # 3 attempts x 0.2s, never the 3600s sleep

    @pytest.mark.parametrize(
        ("kind", "error"), [("rejected", AdapterRejected), ("malformed", MalformedResponse)]
    )
    async def test_permanent_failures_are_not_retried(self, adapter_kwargs, kind, error):
        faults = FaultInjector(kind)
        with pytest.raises(error):
            await MockRetrievalAdapter(faults=faults, **adapter_kwargs).retrieve(QUERY)
        assert faults.calls == 1


@pytest.fixture
def http_rag(adapter_kwargs):
    client = HttpJsonClient("rag", RAG_URL, timeout_s=0.2, api_key="secret-key")
    return HttpRetrievalAdapter(http=client, **adapter_kwargs)


VALID_BODY = {
    "chunks": [
        {
            "chunk_id": "c1",
            "text": "La chlorophylle absorbe la lumière.",
            "source": {"doc_id": "d1", "chunk_id": "c1", "page": 2},
            "score": 0.9,
        }
    ],
    "index_version": "idx-3",
}


class TestHttpAdapter:
    @respx.mock
    async def test_success_sends_contract_and_correlation_headers(self, http_rag):
        route = respx.post(f"{RAG_URL}/v1/retrieve").respond(200, json=VALID_BODY)
        token = request_id_var.set("req-123")
        try:
            response = await http_rag.retrieve(QUERY)
        finally:
            request_id_var.reset(token)
        assert response.simulated is False and response.index_version == "idx-3"
        sent = route.calls.last.request
        assert sent.headers["X-Request-ID"] == "req-123"
        assert sent.headers["Authorization"] == "Bearer secret-key"

    @respx.mock
    async def test_server_errors_are_retried_then_reported(self, http_rag):
        route = respx.post(f"{RAG_URL}/v1/retrieve").respond(503)
        with pytest.raises(AdapterUnavailable):
            await http_rag.retrieve(QUERY)
        assert route.call_count == 3

    @respx.mock
    async def test_client_errors_are_not_retried(self, http_rag):
        route = respx.post(f"{RAG_URL}/v1/retrieve").respond(404)
        with pytest.raises(AdapterRejected):
            await http_rag.retrieve(QUERY)
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"chunks": [{"chunk_id": "c1"}]}),
        ],
    )
    async def test_contract_violations_are_malformed(self, http_rag, response):
        respx.post(f"{RAG_URL}/v1/retrieve").mock(return_value=response)
        with pytest.raises(MalformedResponse):
            await http_rag.retrieve(QUERY)

    @respx.mock
    async def test_network_timeouts_map_to_adapter_timeout(self, http_rag):
        respx.post(f"{RAG_URL}/v1/retrieve").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(AdapterTimeout):
            await http_rag.retrieve(QUERY)


class TestRegistry:
    def test_mocks_used_when_no_url(self, telemetry):
        adapters = build_adapters(Settings(_env_file=None, environment="test"), telemetry)
        modes = adapters.modes()
        assert modes["retrieval"] == "mock" and modes["intent_classifier"] == "disabled"

    def test_url_switches_to_real_service(self, telemetry):
        settings = Settings(_env_file=None, environment="test", rag_service_url=RAG_URL)
        assert build_adapters(settings, telemetry).modes()["retrieval"] == "http"

    def test_missing_service_fails_fast_without_mocks(self, telemetry):
        with pytest.raises(ConfigurationError):
            build_adapters(
                Settings(_env_file=None, environment="staging", allow_mocks=False), telemetry
            )

    def test_production_refuses_mocks(self):
        with pytest.raises(ValueError):
            Settings(_env_file=None, environment="production")

    def test_production_refuses_dev_tokens(self):
        with pytest.raises(ValueError):
            Settings(
                _env_file=None,
                environment="production",
                allow_mocks=False,
                dev_auth_tokens={"x" * 30: {"subject_ref": "s", "role": "teacher"}},
            )

    def test_short_dev_tokens_rejected(self):
        with pytest.raises(ValueError):
            Settings(
                _env_file=None, dev_auth_tokens={"short": {"subject_ref": "s", "role": "student"}}
            )
