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

    def ask(self, question: str, reading_level: str = "standard", k: int | None = None) -> Answer:
        results = self.store.search(question, k=k)
        prompt = load_prompt("answer")
        context = format_context(results, prompt.context_format)
        system, user = prompt.render(reading_level, context=context, question=question)
        raw = self.llm.chat(system, user)
        # Garde-fou : une page citée qui n'est pas celle d'un passage fourni est retirée avant affichage.
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
    ) -> Remediation:
        results = self.store.search(f"{question} {correct_answer}")
        prompt = load_prompt("remediation")
        system, user = prompt.render(
            reading_level,
            context=format_context(results, prompt.context_format),
            question=question,
            student_answer=student_answer,
            correct_answer=correct_answer,
            history="; ".join(history) if history else "aucune",
        )
        return self.llm.structured(system, user, Remediation)
