"""Versioned prompt loader for the formats added by the orchestration layer.

Same convention as the GenAI module (``<name>.v<N>.yaml``, tag ``name@vN``), so prompt versions
appear in the same traces. Reading-level instructions ({style}) are taken from the GenAI module's
``styles`` prompt when it is installed, so both layers stay consistent.

v2 prompts add {language} and {school_level_instruction}; this loader resolves them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK_STYLES = {
    "standard": "Utilise un langage clair et adapté à un élève. Sois concis.",
    "simplifie": (
        "Texte simplifié (FALC) : phrases de 12 mots maximum, une idée par phrase, mots courants, "
        "aucune information absente des extraits."
    ),
}

_FALLBACK_SCHOOL_LEVELS = {
    "primary": "Tu t'adresses à un enfant de primaire. Phrases très courtes, mots simples.",
    "middle": "Tu t'adresses à un élève de collège. Langage clair et direct.",
    "high": "Tu t'adresses à un lycéen. Tu peux utiliser les termes techniques du cours.",
    "university": "Tu t'adresses à un étudiant universitaire. Niveau technique complet.",
    "adult_learning": "Tu t'adresses à un adulte en formation. Ancre dans des situations concrètes.",
}

_LANGUAGE_LABELS: dict[str, str] = {
    "fr": "français",
    "ar": "arabe (العربية)",
    "en": "anglais (English)",
    "es": "espagnol (español)",
    "de": "allemand (Deutsch)",
    "it": "italien (italiano)",
    "pt": "portugais (português)",
}


def _language_label(tag: str) -> str:
    return _LANGUAGE_LABELS.get(tag.split("-")[0], tag)


def _styles() -> dict[str, str]:
    try:
        from tuteur.prompts import load_styles  # type: ignore[import-not-found]
        return load_styles()
    except Exception:
        return _FALLBACK_STYLES


def _school_levels() -> dict[str, str]:
    try:
        from tuteur.prompts import load_school_levels  # type: ignore[import-not-found]
        data = load_school_levels()
        # strip the pydantic/yaml metadata keys
        return {k: v for k, v in data.items() if k not in ("name", "version", "description")}
    except Exception:
        return _FALLBACK_SCHOOL_LEVELS


@dataclass(frozen=True)
class ExtPrompt:
    name: str
    version: int
    system: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(
        self,
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
        **values: str,
    ) -> tuple[str, str]:
        """Render system + user, injecting {style}, {language}, {school_level_instruction}.

        Unknown placeholders in `values` are passed through to str.format().
        """
        styles = _styles()
        levels = _school_levels()

        style = styles.get(reading_level, styles.get("standard", ""))
        lang = _language_label(language)
        level = levels.get(school_level, levels.get("middle", ""))

        def _sub(template: str) -> str:
            t = template
            if "{style}" in t:
                t = t.replace("{style}", style)
            if "{language}" in t:
                t = t.replace("{language}", lang)
            if "{school_level_instruction}" in t:
                t = t.replace("{school_level_instruction}", level)
            return t

        system = _sub(self.system)
        user = _sub(self.user).format(**values) if values else _sub(self.user)
        return system, user


@cache
def load_ext_prompt(name: str, version: int | None = None) -> ExtPrompt:
    versions = sorted(
        int(m.group(1))
        for p in PROMPTS_DIR.glob(f"{name}.v*.yaml")
        if (m := re.search(r"\.v(\d+)\.yaml$", p.name))
    )
    if not versions:
        raise FileNotFoundError(f"no prompt named {name!r}")
    chosen = version or versions[-1]
    data = yaml.safe_load((PROMPTS_DIR / f"{name}.v{chosen}.yaml").read_text(encoding="utf-8"))
    return ExtPrompt(
        name=data["name"], version=data["version"], system=data["system"], user=data["user"]
    )
