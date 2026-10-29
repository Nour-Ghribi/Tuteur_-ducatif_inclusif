import pytest

from tutor_agentic.integrations.mocks import FaultInjector, MockIntentClassifierAdapter
from tutor_agentic.routing import Intent, IntentRouter
from tutor_agentic.routing.router import extract_count, normalize
from tutor_agentic.schemas.common import PresentationFormat


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Explain this chapter simply.", Intent.EXPLAIN),
        ("Explique-moi ce chapitre simplement", Intent.EXPLAIN),
        ("Generate five questions about this topic.", Intent.QUIZ),
        ("Génère 5 questions sur la photosynthèse", Intent.QUIZ),
        ("Quiz me", Intent.QUIZ),
        ("Interroge-moi sur ce cours", Intent.QUIZ),
        ("Give me flashcards.", Intent.FLASHCARDS),
        ("Fais-moi des fiches de révision", Intent.FLASHCARDS),
        ("Create a mind map.", Intent.CONCEPT_MAP),
        ("Fais une carte mentale du chapitre", Intent.CONCEPT_MAP),
        ("Explain this using step-by-step instructions.", Intent.STEPS),
        ("Guide-moi étape par étape", Intent.STEPS),
        ("Show me the key concepts", Intent.CONCEPT_CARDS),
        ("Quelles sont les notions clés ?", Intent.CONCEPT_CARDS),
        ("Compare these concepts", Intent.COMPARISON),
        ("Quelle est la différence entre photosynthèse et respiration ?", Intent.COMPARISON),
        (
            "Give me another exercise because I got the previous one wrong.",
            Intent.NEW_EXERCISE,
        ),
        ("Donne-moi un autre exercice", Intent.NEW_EXERCISE),
    ],
)
async def test_deterministic_routing(message, expected):
    decision = await IntentRouter().decide(message)
    assert decision.intent is expected
    assert decision.source == "rule"
    assert decision.warning is None


async def test_explicit_format_wins_over_text():
    decision = await IntentRouter().decide("Explain please", PresentationFormat.FLASHCARDS)
    assert decision.intent is Intent.FLASHCARDS
    assert decision.source == "explicit"


async def test_unknown_request_defaults_to_explanation_with_warning():
    decision = await IntentRouter().decide("photosynthèse")
    assert decision.intent is Intent.EXPLAIN
    assert decision.source == "default"
    assert decision.warning == "intent_defaulted"


async def test_ambiguous_request_without_classifier_uses_priority():
    decision = await IntentRouter().decide("Quiz me and give me flashcards")
    assert decision.intent is Intent.QUIZ
    assert decision.warning == "intent_ambiguous"
    assert set(decision.candidates) == {Intent.QUIZ, Intent.FLASHCARDS}


async def test_classifier_resolves_ambiguity_within_allowed_set(adapter_kwargs):
    classifier = MockIntentClassifierAdapter(answer="flashcards", **adapter_kwargs)
    decision = await IntentRouter(classifier).decide("Quiz me and give me flashcards")
    assert decision.intent is Intent.FLASHCARDS
    assert decision.source == "classifier"


async def test_clear_requests_never_call_the_classifier(adapter_kwargs):
    classifier = MockIntentClassifierAdapter(answer="quiz", **adapter_kwargs)
    await IntentRouter(classifier).decide("Give me flashcards")
    assert classifier.calls == 0


@pytest.mark.parametrize(
    ("classifier_kwargs", "warning"),
    [
        ({"answer": "delete_database"}, "intent_classifier_rejected"),
        ({"answer": "quiz", "confidence": 0.2}, "intent_classifier_low_confidence"),
        ({"faults": FaultInjector("unavailable")}, "intent_classifier_unavailable"),
    ],
)
async def test_untrusted_classifier_output_falls_back(adapter_kwargs, classifier_kwargs, warning):
    classifier = MockIntentClassifierAdapter(**classifier_kwargs, **adapter_kwargs)
    decision = await IntentRouter(classifier).decide("Quiz me and give me flashcards")
    assert decision.source == "rule"
    assert decision.intent is Intent.QUIZ
    assert decision.warning == warning


@pytest.mark.parametrize(
    ("message", "count"),
    [
        ("Generate five questions", 5),
        ("Donne-moi 3 flashcards", 3),
        ("Génère dix questions", 10),
        ("Generate 99 questions", 20),
        ("Explain photosynthesis", None),
    ],
)
def test_count_extraction(message, count):
    assert extract_count(normalize(message)) == count
