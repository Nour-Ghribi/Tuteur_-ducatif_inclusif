"""Client LLM unique pour toute API compatible OpenAI (Ollama, Groq, Gemini, OpenAI, vLLM...)."""

import json
import time
from dataclasses import dataclass, field
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from tuteur.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMCall:
    """Trace d'un appel, prête à être envoyée à MLflow plus tard."""

    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    extra: dict = field(default_factory=dict)


class LLM:
    def __init__(
        self,
        settings: Settings | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
    ):
        self.settings = settings or get_settings()
        self.model = model or self.settings.llm_model
        self.temperature = self.settings.llm_temperature if temperature is None else temperature
        # max_retries élevé : les offres gratuites (Groq...) renvoient souvent des 429, le client attend puis réessaie.
        self.client = OpenAI(
            base_url=base_url or self.settings.llm_base_url,
            api_key=api_key or self.settings.llm_api_key,
            max_retries=8,
        )
        self.calls: list[LLMCall] = []

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        t0 = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **kwargs,
        )
        usage = resp.usage
        self.calls.append(
            LLMCall(
                model=self.model,
                latency_s=time.perf_counter() - t0,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )
        )
        return resp.choices[0].message.content or ""

    def structured(self, system: str, user: str, schema: type[T], retries: int = 1) -> T:
        """Demande une sortie JSON et la valide avec Pydantic ; en cas d'échec, renvoie l'erreur au modèle."""
        prompt = f"{user}\n\nRéponds UNIQUEMENT avec un JSON valide respectant ce schéma :\n" + json.dumps(
            schema.model_json_schema(), ensure_ascii=False
        )
        for attempt in range(retries + 1):
            raw = self.chat(system, prompt, json_mode=True)
            try:
                return schema.model_validate_json(_strip_fences(raw))
            except ValidationError as e:
                if attempt == retries:
                    raise
                prompt += f"\n\nTa réponse précédente était invalide :\n{e}\nCorrige-la."
        raise AssertionError("unreachable")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return text
