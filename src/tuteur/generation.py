"""Pipelines GenAI : question/réponse RAG, génération de quiz, reprise après échec."""

from tuteur.citations import check_citations, strip_invalid_citations
from tuteur.llm import LLM
from tuteur.prompts import DEFAULT_CONTEXT_FORMAT, load_prompt
from tuteur.schemas import Answer, Difficulty, Quiz, Remediation
from tuteur.vectorstore import SearchResult, VectorStore


def format_context(results: list[SearchResult], fmt: str = DEFAULT_CONTEXT_FORMAT) -> str:
    """`fmt` vient du prompt (champ context_format) : la présentation des passages fait partie
    de l'expérience versionnée, comme le texte du prompt."""
    return "\n\n".join(
        fmt.format(i=i, page=r.metadata["page"], source=r.metadata["source"], text=r.text)
        for i, r in enumerate(results, 1)
    )


class Tutor:
    def __init__(self, store: VectorStore | None = None, llm: LLM | None = None):
        self.store = store or VectorStore()
        self.llm = llm or LLM()

    def ask(
        self,
        question: str,
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
        k: int | None = None,
    ) -> Answer:
        results = self.store.search(question, k=k)
        prompt = load_prompt("answer")
        context = format_context(results, prompt.context_format)
        system, user = prompt.render(
            reading_level,
            language=language,
            school_level=school_level,
            context=context,
            question=question,
        )
        raw = self.llm.chat(system, user)
        pages = {r.metadata["page"] for r in results}
        return Answer(
            text=strip_invalid_citations(raw, pages),
            raw_text=raw,
            invalid_citations=check_citations(raw, pages).invalid,
            sources=[{"page": r.metadata["page"], "source": r.metadata["source"], "score": round(r.score, 3)}
                     for r in results],
            contexts=[r.text for r in results],
            context_pages=[r.metadata["page"] for r in results],
            prompt=prompt.tag,
        )

    def quiz(
        self,
        *,
        topic: str | None = None,
        doc_id: str | None = None,
        pages: list[int] | None = None,
        n: int = 5,
        difficulty: Difficulty = "moyen",
        types: tuple[str, ...] = ("qcm", "vrai_faux", "flashcard"),
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
    ) -> Quiz:
        """Quiz sur un thème (recherche sémantique) ou sur des pages précises d'un document (chapitre)."""
        if doc_id and pages:
            results = self.store.get_pages(doc_id, pages)
        elif topic:
            results = self.store.search(topic, k=max(self.store.settings.top_k, n))
        else:
            raise ValueError("Préciser `topic` ou (`doc_id` et `pages`).")
        if not results:
            raise ValueError("Aucun passage trouvé dans la base pour générer le quiz.")

        prompt = load_prompt("quiz")
        system, user = prompt.render(
            reading_level,
            language=language,
            school_level=school_level,
            context=format_context(results, prompt.context_format),
            n=n,
            difficulty=difficulty,
            types=", ".join(types),
        )
        return self.llm.structured(system, user, Quiz)

    def remediate(
        self,
        question: str,
        student_answer: str,
        correct_answer: str,
        history: list[str] | None = None,
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
    ) -> Remediation:
        results = self.store.search(f"{question} {correct_answer}")
        prompt = load_prompt("remediation")
        system, user = prompt.render(
            reading_level,
            language=language,
            school_level=school_level,
            context=format_context(results, prompt.context_format),
            question=question,
            student_answer=student_answer,
            correct_answer=correct_answer,
            history="; ".join(history) if history else "aucune",
        )
        return self.llm.structured(system, user, Remediation)

    def adaptive_remediate(
        self,
        *,
        strategy_id: str,
        question: str,
        student_answer: str,
        correct_answer: str,
        competence: str,
        history: list[str] | None = None,
        reading_level: str = "standard",
        language: str = "fr",
        school_level: str = "middle",
    ):
        """Generate one strategy-specific, grounded remediation without changing legacy APIs."""
        from tuteur.adaptive.models import (
            ACTION_IDS,
            REMEDIATION_SCHEMAS,
            GuidedHint,
            normalize_skill_label,
        )

        if strategy_id not in ACTION_IDS:
            raise ValueError(f"Unknown remediation strategy: {strategy_id}")
        results = self.store.search(f"{question} {correct_answer} {competence}")
        if not results:
            raise ValueError("No retrieved course passage is available for remediation")
        prompt_name = f"remediation_{strategy_id[:2].lower()}"
        prompt = load_prompt(prompt_name)
        system, user = prompt.render(
            reading_level,
            language=language,
            school_level=school_level,
            context=format_context(results, prompt.context_format),
            question=question,
            student_answer=student_answer,
            correct_answer=correct_answer,
            competence=competence,
            history="; ".join(history) if history else "aucune",
        )
        schema = REMEDIATION_SCHEMAS[strategy_id]
        output = self.llm.structured(system, user, schema)
        allowed_pages = {int(result.metadata["page"]) for result in results}
        if not set(output.source_pages) <= allowed_pages:
            raise ValueError("Remediation cited a page outside retrieved course passages")
        if normalize_skill_label(output.competence) != normalize_skill_label(competence):
            raise ValueError("Follow-up competence differs from the failed question skill")
        if normalize_skill_label(output.retry_question.competence) != normalize_skill_label(competence):
            raise ValueError("Follow-up question does not preserve the stable skill")
        def normalize_text(value: str) -> str:
            return " ".join(value.casefold().split()).strip(" .?!")
        if normalize_text(output.retry_question.question) == normalize_text(question):
            raise ValueError("Follow-up question must differ from the failed question")
        if output.retry_question.type not in {"qcm", "vrai_faux"}:
            raise ValueError("MVP follow-up must be deterministically gradable")
        if isinstance(output, GuidedHint):
            answer = normalize_text(correct_answer)
            combined = normalize_text(f"{output.hint} {output.guiding_question}")
            # This is one guard among prompt constraints, structure and human-visible provenance;
            # it is not claimed to prove semantic non-disclosure.
            if len(answer) >= 3 and answer in combined:
                raise ValueError("Guided hint appears to disclose the complete answer")
        return output
