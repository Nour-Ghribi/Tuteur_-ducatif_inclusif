from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM : n'importe quelle API compatible OpenAI (Ollama, Groq, Gemini, OpenAI...)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b"
    llm_api_key: str = "ollama"
    llm_temperature: float = 0.3
    # Version des prompts (vide = dernière version de chaque prompt)
    prompt_version: int | None = None
    # Juge pour l'évaluation (RAGAS) : peut être un autre fournisseur que le générateur.
    # Champs vides = mêmes valeurs que pour le LLM générateur.
    eval_judge_model: str = ""
    eval_judge_base_url: str = ""
    eval_judge_api_key: str = ""

    @property
    def judge(self) -> dict:
        """model / base_url / api_key du juge, avec repli sur le LLM générateur."""
        return {
            "model": self.eval_judge_model or self.llm_model,
            "base_url": self.eval_judge_base_url or self.llm_base_url,
            "api_key": self.eval_judge_api_key or self.llm_api_key,
        }

    # RAG
    embedding_model: str = "intfloat/multilingual-e5-small"
    chroma_dir: Path = Path("data/chroma")
    images_dir: Path = Path("data/images")
    collection: str = "cours"
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5
    # « dense » (embeddings seuls) ou « hybride » (embeddings + BM25, fusion RRF).
    # Hybride par défaut : hit@5 = 1.0 sur questions exactes ET reformulées (dense : 0.94 / 1.0).
    search_mode: str = "hybride"
    hybrid_pool: int = 20  # candidats pris dans chaque classement avant fusion

    # VLM for image description at ingestion time (optional).
    # Set VISION_MODEL to enable; leave empty to skip image description.
    # Any OpenAI-compatible vision API works: Ollama+LLaVA, Gemini, GPT-4o, Qwen2-VL…
    vision_model: str = ""
    vision_base_url: str = ""
    vision_api_key: str = "none"
    vision_language: str = "fr"      # language for VLM descriptions
    vision_timeout_s: float = 60.0   # per-image timeout

    # MVP adaptatif. MOCK_DEMO n'effectue aucun appel LLM externe.
    adaptive_mode: str = "mock"
    adaptive_db_path: Path = Path("data/adaptive_tutor.sqlite3")
    adaptive_policy_checkpoint: Path = Path("models/linucb_demo_v1.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
