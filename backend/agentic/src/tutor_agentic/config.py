"""Runtime configuration, loaded from ``TUTOR_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class DevIdentity(BaseModel):
    """Pseudonymous identity bound to a development token. Never a real person."""

    subject_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    role: Literal["student", "teacher"]
    class_ids: list[str] = Field(default_factory=list, max_length=50)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TUTOR_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Environment = "development"
    allow_mocks: bool = True

    # mock: simulated services | tuteur: in-process GenAI+RAG module | http: teammate services by URL
    genai_backend: Literal["mock", "tuteur", "http"] = "mock"
    images_dir: Path = Path("data/images")
    adapted_images_dir: Path = Path("data/images_adapted")
    vision_model: str = ""
    vision_base_url: str = ""
    vision_api_key: SecretStr | None = None

    rag_service_url: AnyHttpUrl | None = None
    genai_service_url: AnyHttpUrl | None = None
    rl_service_url: AnyHttpUrl | None = None
    learning_records_service_url: AnyHttpUrl | None = None
    inclusion_service_url: AnyHttpUrl | None = None
    service_api_key: SecretStr | None = None

    adapter_timeout_s: float = Field(8.0, gt=0, le=60)
    adapter_max_retries: int = Field(2, ge=0, le=5)
    adapter_backoff_s: float = Field(0.25, ge=0, le=5)
    genai_timeout_s: float = Field(
        60.0, gt=0, le=300
    )  # in-process LLM calls are slower than HTTP hops
    graph_timeout_s: float = Field(90.0, gt=0, le=300)
    max_generation_attempts: int = Field(2, ge=1, le=4)
    rag_top_k: int = Field(5, ge=1, le=20)

    intent_classifier_enabled: bool = False
    intent_classifier_min_confidence: float = Field(0.6, ge=0, le=1)

    issued_item_ttl_s: int = Field(3600, ge=60, le=86_400)
    dev_auth_tokens: dict[str, DevIdentity] = Field(default_factory=dict)

    @property
    def is_development(self) -> bool:
        return self.environment in ("development", "test")

    @model_validator(mode="after")
    def _guard_unsafe_settings(self) -> Settings:
        if self.environment == "production" and self.allow_mocks:
            raise ValueError("TUTOR_ALLOW_MOCKS must be false in production")
        if self.dev_auth_tokens and not self.is_development:
            raise ValueError("TUTOR_DEV_AUTH_TOKENS is only allowed in development/test")
        if any(len(token) < 24 for token in self.dev_auth_tokens):
            raise ValueError("development tokens must be at least 24 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
