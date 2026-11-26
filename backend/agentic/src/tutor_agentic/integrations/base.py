"""Resilience and HTTP plumbing shared by every adapter.

Retries, timeouts and telemetry live here once, so graph nodes only see typed results or
typed ``AdapterError``s.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..errors import (
    AdapterError,
    AdapterRejected,
    AdapterTimeout,
    AdapterUnavailable,
    MalformedResponse,
)
from ..telemetry import Telemetry, request_id_var

T = TypeVar("T")
R = TypeVar("R", bound=BaseModel)


@dataclass(frozen=True)
class ResiliencePolicy:
    timeout_s: float = 8.0
    max_retries: int = 2
    backoff_s: float = 0.25


class ResilientAdapter:
    """Base class: wraps each operation with a per-attempt timeout and bounded retries."""

    service: ClassVar[str] = "unknown"

    def __init__(self, policy: ResiliencePolicy, telemetry: Telemetry) -> None:
        self._policy = policy
        self._telemetry = telemetry

    async def _invoke(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        started = time.perf_counter()
        attempts = 0
        error: AdapterError | None = None
        for attempt in range(self._policy.max_retries + 1):
            attempts += 1
            try:
                async with asyncio.timeout(self._policy.timeout_s):
                    result = await call()
            except TimeoutError:
                error = AdapterTimeout(
                    self.service, operation, f"no answer within {self._policy.timeout_s}s"
                )
            except ValidationError as exc:
                error = MalformedResponse(
                    self.service, operation, f"{exc.error_count()} contract violation(s)"
                )
            except AdapterError as exc:
                error = exc
            else:
                self._record(operation, "success", started, attempts)
                return result
            if not error.retryable or attempt == self._policy.max_retries:
                break
            await asyncio.sleep(self._policy.backoff_s * (2**attempt))
        assert error is not None
        self._record(operation, "failure", started, attempts, error.code)
        raise error

    def _record(
        self,
        operation: str,
        outcome: str,
        started: float,
        attempts: int,
        error_code: str | None = None,
    ) -> None:
        self._telemetry.adapter_call(
            service=self.service,
            operation=operation,
            outcome=outcome,
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=attempts,
            error_code=error_code,
        )

    async def aclose(self) -> None:
        return None


class HttpJsonClient:
    """Minimal JSON-over-HTTP client mapping transport failures to typed adapter errors."""

    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        timeout_s: float,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._service = service
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=headers
        )

    async def request(
        self,
        method: str,
        operation: str,
        path: str,
        response_model: type[R],
        *,
        payload: BaseModel | None = None,
        params: dict[str, Any] | None = None,
    ) -> R:
        headers = {}
        if request_id := request_id_var.get():
            headers["X-Request-ID"] = request_id
        try:
            response = await self._client.request(
                method,
                path,
                json=payload.model_dump(mode="json", exclude_none=True) if payload else None,
                params=params,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeout(self._service, operation, "HTTP timeout") from exc
        except httpx.TransportError as exc:
            raise AdapterUnavailable(self._service, operation, type(exc).__name__) from exc

        if response.status_code >= 500 or response.status_code == 429:
            raise AdapterUnavailable(self._service, operation, f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise AdapterRejected(self._service, operation, f"HTTP {response.status_code}")
        try:
            return response_model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise MalformedResponse(self._service, operation, "response violates contract") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
