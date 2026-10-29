"""Prompts versionnés : un fichier par version (`answer.v1.yaml`, `answer.v2.yaml`...), suivis par Git.

Par défaut on charge la dernière version ; `PROMPT_VERSION=N` dans `.env` (ou `--prompts N` pour
`tuteur eval`) fige chaque famille à sa dernière version ≤ N (un « instantané » des prompts),
pour rejouer ou comparer une expérience.
Chaque résultat enregistre ses tags (`answer@v2`...) pour la traçabilité MLOps.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from tuteur.config import get_settings

PROMPTS_DIR = Path(__file__).parent
READING_LEVELS = ("standard", "simplifie")
# Présentation de chaque passage dans {context} ; un prompt peut la redéfinir (champ context_format).
DEFAULT_CONTEXT_FORMAT = "[p. {page}] {text}"


def available_versions(name: str) -> list[int]:
    return sorted(int(m.group(1)) for p in PROMPTS_DIR.glob(f"{name}.v*.yaml")
                  if (m := re.fullmatch(rf"{name}\.v(\d+)\.yaml", p.name)))


def _resolve_version(name: str, version: int | None) -> int:
    versions = available_versions(name)
    if not versions:
        raise FileNotFoundError(f"Aucun prompt '{name}' dans {PROMPTS_DIR}")
    wanted = version or get_settings().prompt_version
    if wanted is None:
        return versions[-1]
    candidates = [v for v in versions if v <= wanted]
    if not candidates:
        raise ValueError(f"Prompt '{name}' : aucune version ≤ v{wanted} (versions : {versions})")
    return candidates[-1]


@cache
def _load_yaml(name: str, version: int) -> dict:
    return yaml.safe_load((PROMPTS_DIR / f"{name}.v{version}.yaml").read_text(encoding="utf-8"))


def load_styles(version: int | None = None) -> dict:
    return _load_yaml("styles", _resolve_version("styles", version))


def styles_tag() -> str:
    return f"styles@v{load_styles()['version']}"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str
    styles: dict
    context_format: str = DEFAULT_CONTEXT_FORMAT

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(self, reading_level: str = "standard", **kwargs) -> tuple[str, str]:
        # Consignes d'accessibilité (styles.vN.yaml) injectées dans {style}.
        return self.system.format(style=self.styles[reading_level]), self.user.format(**kwargs)


def load_prompt(name: str, version: int | None = None) -> Prompt:
    data = _load_yaml(name, _resolve_version(name, version))
    return Prompt(name=data["name"], version=data["version"], system=data["system"], user=data["user"],
                  styles=load_styles(version),
                  context_format=data.get("context_format", DEFAULT_CONTEXT_FORMAT))
