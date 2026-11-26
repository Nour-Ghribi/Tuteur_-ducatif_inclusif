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

# IETF language tag → human-readable label used inside prompts
LANGUAGE_LABELS: dict[str, str] = {
    "fr": "français",
    "ar": "arabe (العربية)",
    "en": "anglais (English)",
    "es": "espagnol (español)",
    "de": "allemand (Deutsch)",
    "it": "italien (italiano)",
    "pt": "portugais (português)",
}


def language_label(tag: str) -> str:
    """Returns a human-readable language name for the prompt, e.g. 'ar' → 'arabe (العربية)'."""
    return LANGUAGE_LABELS.get(tag.split("-")[0], tag)


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


def load_school_levels(version: int | None = None) -> dict:
    """Returns the school_level instruction strings keyed by level name."""
    return _load_yaml("school_levels", _resolve_version("school_levels", version))


def styles_tag() -> str:
    return f"styles@v{load_styles()['version']}"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str
    styles: dict
    school_levels: dict
    context_format: str = DEFAULT_CONTEXT_FORMAT

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(
        self,
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
        **kwargs,
    ) -> tuple[str, str]:
        """Render system + user prompts.

        Injects:
          {style}                  — reading-level instructions (accessibility)
          {language}               — human-readable language label
          {school_level_instruction} — tone instruction for the student's school level

        Both placeholders are optional in a prompt: prompts that don't have
        them (older versions) are unaffected.
        """
        style_text = self.styles.get(reading_level, self.styles.get("standard", ""))
        lang_label = language_label(language)
        level_text = self.school_levels.get(school_level, self.school_levels.get("middle", ""))

        def _fmt(template: str) -> str:
            # Replace known placeholders; leave unknown ones untouched so callers
            # can still pass arbitrary **kwargs without KeyError.
            t = template
            if "{style}" in t:
                t = t.replace("{style}", style_text)
            if "{language}" in t:
                t = t.replace("{language}", lang_label)
            if "{school_level_instruction}" in t:
                t = t.replace("{school_level_instruction}", level_text)
            return t

        system = _fmt(self.system)
        user = _fmt(self.user).format(**kwargs)
        return system, user


def load_prompt(name: str, version: int | None = None) -> Prompt:
    data = _load_yaml(name, _resolve_version(name, version))
    return Prompt(
        name=data["name"],
        version=data["version"],
        system=data["system"],
        user=data["user"],
        styles=load_styles(version),
        school_levels=load_school_levels(version),
        context_format=data.get("context_format", DEFAULT_CONTEXT_FORMAT),
    )
