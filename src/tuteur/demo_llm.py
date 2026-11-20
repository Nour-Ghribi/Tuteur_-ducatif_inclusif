"""Deterministic offline LLM and lexical store for the clearly labelled MOCK DEMO."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from tuteur.llm import LLM
from tuteur.vectorstore import SearchResult


class OfflineDemoStore:
    def __init__(self, text: str, source: str = "photosynthese.md"):
        self.text = text
        self.source = source
        self.settings = SimpleNamespace(top_k=5)

    @classmethod
    def from_path(cls, path: str | Path) -> OfflineDemoStore:
        path = Path(path)
        return cls(path.read_text(encoding="utf-8"), path.name)

    def search(self, query: str, k: int | None = None, **kwargs) -> list[SearchResult]:
        paragraphs = [part.strip() for part in self.text.split("\n\n") if part.strip()]
        terms = {word.casefold() for word in re.findall(r"\w+", query) if len(word) > 3}
        scored = sorted(
            paragraphs,
            key=lambda part: sum(term in part.casefold() for term in terms),
            reverse=True,
        )
        return [
            SearchResult(f"offline-{i}", text, {"page": 1, "source": self.source}, 1.0 / i)
            for i, text in enumerate(scored[: (k or 5)], 1)
        ]

    def get_pages(self, doc_id: str, pages: list[int]) -> list[SearchResult]:
        return self.search(doc_id)

    def documents(self) -> dict[str, str]:
        return {"offline-demo": self.source}


class DeterministicDemoLLM(LLM):
    model = "deterministic-mock-v1"

    def __init__(self):
        self.calls = []
        self.quiz_calls = 0

    @staticmethod
    def _competence(user: str) -> str:
        match = re.search(r"COMPETENCE:\s*([^\n]+)", user)
        return match.group(1).strip() if match else "photosynthèse"

    @staticmethod
    def _quiz_item(competence: str, variant: int = 0) -> dict:
        if variant % 2:
            return {
                "type": "vrai_faux",
                "question": "La chlorophylle capte une partie de la lumière.",
                "choices": ["Vrai", "Faux"],
                "answer": "Vrai",
                "explanation": "Le cours associe la chlorophylle à la capture de lumière.",
                "difficulty": "facile",
                "competence": competence,
                "source_pages": [1],
            }
        return {
            "type": "qcm",
            "question": "Quel élément aide la plante à capter la lumière ?",
            "choices": ["La chlorophylle", "Les racines", "Le dioxyde de carbone", "L'eau"],
            "answer": "La chlorophylle",
            "explanation": "La chlorophylle capte l'énergie lumineuse.",
            "difficulty": "facile",
            "competence": competence,
            "source_pages": [1],
        }

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        self.calls.append((system, user, json_mode))
        strategy_match = re.search(r"STRATEGY_ID:\s*(A\d_[a-z_]+)", system)
        if not strategy_match:
            item = self._quiz_item("photosynthèse", self.quiz_calls)
            self.quiz_calls += 1
            return json.dumps({"items": [item]}, ensure_ascii=False)
        strategy = strategy_match.group(1)
        skill = self._competence(user)
        # Alternate away from the failed item even after several quiz generations in one
        # Streamlit process. The adaptive validator intentionally rejects an identical retry.
        failed_is_true_false = "La chlorophylle capte une partie de la lumière." in user
        retry = self._quiz_item(skill, 0 if failed_is_true_false else 1)
        base = {
            "strategy_id": strategy,
            "diagnostic": "La notion principale semble avoir été confondue.",
            "competence": skill,
            "source_pages": [1],
            "retry_question": retry,
        }
        if strategy == "A0_guided_hint":
            base |= {
                "hint": "Pense au pigment vert présent dans les feuilles.",
                "guiding_question": "Quel rôle un pigment peut-il jouer avec la lumière ?",
            }
        elif strategy == "A1_simplified_explanation":
            base |= {
                "explanation": "La feuille possède un pigment vert. Il aide à utiliser la lumière.",
                "key_points": ["La feuille contient un pigment.", "Ce pigment utilise la lumière."],
            }
        elif strategy == "A2_worked_example":
            base |= {
                "example_problem": "Une feuille reçoit de la lumière : quel élément la capte ?",
                "steps": ["Repérer le pigment de la feuille.", "Relier ce pigment à la lumière."],
                "conclusion": "Le pigment vert permet de capter la lumière.",
            }
        elif strategy == "A3_scaffolded_mcq":
            base |= {
                "scaffold_steps": ["Cherche d'abord le pigment mentionné dans le cours."],
                "scaffolded_mcq": self._quiz_item(skill, 0),
            }
        else:
            base |= {
                "summary": "La photosynthèse utilise la lumière captée dans la feuille.",
                "key_points": ["Un pigment vert est présent.", "La lumière fournit de l'énergie."],
                "common_error": "Ne pas confondre ce pigment avec une substance absorbée par les racines.",
            }
        return json.dumps(base, ensure_ascii=False)
