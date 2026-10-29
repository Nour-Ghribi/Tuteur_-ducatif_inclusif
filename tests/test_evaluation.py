import json

from tuteur.evaluation import light_judge, readability
from tuteur.llm import LLM


class FakeJudge(LLM):
    def __init__(self, verdict: dict):
        self.verdict = verdict

    def chat(self, system, user, json_mode=False):
        return json.dumps(self.verdict)


def test_light_judge_scores():
    judge = FakeJudge({
        "claims": [{"claim": "a", "supported": True}, {"claim": "b", "supported": True},
                   {"claim": "c", "supported": False}, {"claim": "d", "supported": True}],
        "answers_question": "oui",
        "matches_reference": "partiellement",
    })
    sample = {"id": "x", "question": "q", "reference": "r", "answer": "a", "contexts": ["ctx"]}
    assert light_judge(judge, sample) == {
        "faithfulness": 0.75, "answer_relevancy": 1.0, "answer_correctness": 0.5, "unsupported_claims": ["c"],
    }


def test_light_judge_failure_returns_empty():
    class Broken(FakeJudge):
        def chat(self, *a, **kw):
            raise RuntimeError("quota")

    assert light_judge(Broken({}), {"id": "x", "question": "q", "reference": "r", "answer": "a", "contexts": []}) == {}


def test_simple_text_is_more_readable_than_complex_text():
    simple = "La plante boit de l'eau. Elle prend la lumière. Elle fait du sucre."
    complexe = ("La photosynthèse constitue un processus biochimique extraordinairement sophistiqué "
                "permettant la transformation de l'énergie lumineuse en énergie chimique utilisable.")
    assert readability(simple)["words_per_sentence"] < readability(complexe)["words_per_sentence"]
    assert readability(simple)["kandel_moles"] > readability(complexe)["kandel_moles"]


def test_markdown_is_ignored():
    assert readability("**Bonjour** le monde.")["words"] == 3


def test_citations_are_not_sentences():
    r = readability("La plante fait du sucre. [p. 1]\nElle rejette du dioxygène. [p. 1]")
    assert r["words"] == 9 and r["words_per_sentence"] == 4.5  # 2 phrases, les [p. 1] ne comptent pas


def test_empty_text():
    assert readability("")["words"] == 0
