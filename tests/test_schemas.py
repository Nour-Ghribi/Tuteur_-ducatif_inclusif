import pytest
from pydantic import ValidationError

from tuteur.prompts import load_prompt
from tuteur.schemas import QuizItem

BASE = dict(question="?", explanation="car", difficulty="facile", competence="x")


def test_valid_qcm():
    QuizItem(type="qcm", choices=["a", "b", "c", "d"], answer="b", **BASE)


def test_qcm_answer_must_be_a_choice():
    with pytest.raises(ValidationError):
        QuizItem(type="qcm", choices=["a", "b", "c", "d"], answer="e", **BASE)


def test_qcm_needs_four_choices():
    with pytest.raises(ValidationError):
        QuizItem(type="qcm", choices=["a", "b"], answer="a", **BASE)


def test_vrai_faux_answer():
    with pytest.raises(ValidationError):
        QuizItem(type="vrai_faux", choices=["Vrai", "Faux"], answer="Oui", **BASE)


@pytest.mark.parametrize("name", ["answer", "quiz", "remediation"])
@pytest.mark.parametrize("level", ["standard", "simplifie"])
def test_prompts_render(name, level):
    p = load_prompt(name)
    kwargs = dict(context="ctx", question="q", n=3, difficulty="facile", types="qcm",
                  student_answer="a", correct_answer="b", history="aucune")
    system, user = p.render(level, **kwargs)
    assert "{" not in system and "ctx" in user
    assert p.tag == f"{name}@v{p.version}"
