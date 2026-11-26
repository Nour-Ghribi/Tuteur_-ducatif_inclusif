"""Versioned prompt loader for the formats added by the orchestration layer.

Same convention as the GenAI module (``<name>.v<N>.yaml``, tag ``name@vN``), so prompt versions
appear in the same traces. Reading-level instructions ({style}) are taken from the GenAI module's
``styles`` prompt when it is installed, so both layers stay consistent.
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


def _styles() -> dict[str, str]:
    try:
        from tuteur.prompts import load_styles  # type: ignore[import-not-found]

        return load_styles()
    except Exception:  # GenAI module absent or incompatible: keep working with a built-in copy
        return _FALLBACK_STYLES


@dataclass(frozen=True)
class ExtPrompt:
    name: str
    version: int
    system: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(self, reading_level: str = "standard", **values: str) -> tuple[str, str]:
        styles = _styles()
        style = styles.get(reading_level, styles["standard"])
        return self.system.replace("{style}", style), self.user.format(**values)


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
