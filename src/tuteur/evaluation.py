"""Évaluation du tuteur sur un jeu de référence.

Quatre familles de métriques :
- retrieval (sans LLM)    : hit@1, hit@3, hit@k, MRR, bonne source en 1er
- juge LLM, deux modes    : « leger » (défaut) = 1 appel par réponse → faithfulness (part des affirmations
                            supportées par le contexte), answer relevancy, answer correctness ;
                            « ragas » = métriques RAGAS officielles, ≈3 appels par réponse
                            (faithfulness, answer relevancy, context recall, + context precision avec --complet)
- inclusion (sans LLM)    : lisibilité des réponses standard vs simplifiées (mots/phrase, score Kandel-Moles)
- comportement            : refus des questions hors cours, remédiation qui ne répète pas la question

Chaque étape est enregistrée dans eval/runs/<label>/ : relancer la même commande reprend là où
elle s'est arrêtée (utile avec les quotas journaliers des API gratuites). Les scores RAGAS
manquants (quota épuisé) sont recalculés au lancement suivant.
"""

import json
import re
import statistics
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

from tuteur.citations import check_citations
from tuteur.config import Settings, get_settings
from tuteur.generation import Tutor
from tuteur.llm import LLM
from tuteur.prompts import READING_LEVELS, load_prompt, styles_tag
from tuteur.vectorstore import VectorStore

EVAL_DIR = Path("eval")
DEFAULT_METRICS = ("faithfulness", "answer_relevancy", "context_recall")
# Ces métriques ne jugent que les passages retrouvés : inutile de les recalculer en mode simplifié.
CONTEXT_METRICS = {"context_recall", "llm_context_precision_with_reference"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- Retrieval ----------

def retrieval_metrics(store: VectorStore, refs: list[dict], k: int) -> dict:
    hits1, hits3, hitsk, rr, src1 = [], [], [], [], []
    for r in refs:
        results = store.search(r["question"], k=k)
        ranks = [i for i, res in enumerate(results, 1) if r["evidence"].lower() in res.text.lower()]
        first = ranks[0] if ranks else None
        hits1.append(first == 1)
        hits3.append(first is not None and first <= 3)
        hitsk.append(first is not None)
        rr.append(1 / first if first else 0.0)
        src1.append(results[0].metadata["source"] == r["source"])
    return {
        "hit@1": statistics.mean(hits1),
        "hit@3": statistics.mean(hits3),
        f"hit@{k}": statistics.mean(hitsk),
        "mrr": statistics.mean(rr),
        "source@1": statistics.mean(src1),
    }


# ---------- Lisibilité (français) ----------

_VOWELS = re.compile(r"[aeiouyàâäéèêëîïôöùûü]+", re.I)


def _syllables(word: str) -> int:
    n = len(_VOWELS.findall(word))
    if word.lower().endswith("e") and n > 1:  # e muet final
        n -= 1
    return max(n, 1)


def readability(text: str) -> dict:
    """Mots par phrase et score de Kandel-Moles (Flesch adapté au français ; plus haut = plus facile)."""
    text = re.sub(r"\[\s*p\.\s*\d+[^\]]*\]", " ", text)  # retire les citations [p. N]
    text = re.sub(r"[*_#`>\[\]]", " ", text)  # retire le markdown
    sentences = [s for s in re.split(r"[.!?:;\n]+", text) if re.search(r"\w", s)]
    words = re.findall(r"[A-Za-zÀ-ÿ0-9’'-]+", text)
    if not sentences or not words:
        return {"words": 0, "words_per_sentence": 0.0, "kandel_moles": 0.0}
    wps = len(words) / len(sentences)
    spw = sum(_syllables(w) for w in words) / len(words)
    return {"words": len(words), "words_per_sentence": wps, "kandel_moles": 207 - 1.015 * wps - 73.6 * spw}


# ---------- Citations (sans LLM) ----------

def citation_metrics(store: VectorStore, rows: list[dict]) -> dict:
    """Mesure sur la réponse BRUTE du LLM (avant le garde-fou qui retire les citations invalides) :
    - citation_rate     : part des réponses qui citent au moins une page
    - citation_validity : part des pages citées qui sont celles d'un passage fourni
    - citation_hit_pdf  : questions sur le PDF (seul document multi-pages) dont une page citée
                          contient vraiment l'information attendue (evidence)"""
    data = store.collection.get(include=["documents", "metadatas"])
    page_of = {t: m["page"] for t, m in zip(data["documents"], data["metadatas"])}
    chunks = list(zip(data["documents"], data["metadatas"]))

    n_cited = n_invalid = 0
    citing, hits = [], []
    for row in rows:
        raw = row.get("raw_answer") or row["answer"]
        # les premiers runs n'enregistraient pas les pages : on les retrouve via le texte des passages
        pages = set(row.get("context_pages") or (page_of[c] for c in row["contexts"] if c in page_of))
        check = check_citations(raw, pages)
        n_cited += check.n_citations
        n_invalid += len(check.invalid)
        citing.append(bool(check.cited))
        if row["source"].endswith(".pdf"):
            evidence_pages = {m["page"] for t, m in chunks
                              if m["source"] == row["source"] and row["evidence"].lower() in t.lower()}
            hits.append(bool(set(check.cited) & evidence_pages))
    return {
        "citation_rate": statistics.mean(citing),
        "citation_validity": 1 - n_invalid / n_cited if n_cited else None,
        "citation_hit_pdf": statistics.mean(hits) if hits else None,
    }


# ---------- Comportement ----------

class Refusal(BaseModel):
    refuses: bool


def judge_refusal(judge: LLM, question: str, answer: str) -> bool | None:
    try:
        verdict = judge.structured(
            "Tu évalues un tuteur. Réponds en JSON.",
            f"Question : {question}\nRéponse du tuteur : {answer}\n\n"
            "Le tuteur indique-t-il que l'information n'est pas dans le cours, SANS donner la réponse "
            "à partir de ses propres connaissances ? refuses = true si oui.",
            Refusal,
        )
    except Exception as e:  # quota épuisé... : on réessaiera au prochain lancement
        print(f"  ! juge indisponible ({type(e).__name__})")
        return None
    return verdict.refuses


def remediation_rows(tutor: Tutor, cases: list[dict], reading_level: str) -> list[dict]:
    """Similarité cosinus entre la question ratée et le nouvel exercice : trop proche = simple répétition."""
    rows = []
    for c in cases:
        rem = tutor.remediate(c["question"], c["student_answer"], c["correct_answer"], reading_level=reading_level)
        a, b = tutor.store._embed([c["question"], rem.exercise.question], "query")
        rows.append({
            "id": c["id"],
            "question": c["question"],
            "diagnostic": rem.diagnostic,
            "explanation": rem.explanation,
            "exercise": rem.exercise.model_dump(),
            "similarity": float(np.dot(a, b)),
            **readability(rem.explanation),
        })
    return rows


# ---------- Juge léger : 1 appel par réponse, critères inspirés de RAGAS ----------

class Claim(BaseModel):
    claim: str
    supported: bool


class LightJudgement(BaseModel):
    claims: list[Claim]
    answers_question: Literal["oui", "partiellement", "non"]
    matches_reference: Literal["oui", "partiellement", "non"]


_GRADE = {"oui": 1.0, "partiellement": 0.5, "non": 0.0}
LIGHT_METRICS = ("faithfulness", "answer_relevancy", "answer_correctness")

LIGHT_JUDGE_PROMPT = """Tu évalues la réponse d'un tuteur. Sois strict et factuel.

EXTRAITS DU COURS (seule source autorisée) :
{context}

QUESTION : {question}
RÉPONSE DE RÉFÉRENCE : {reference}
RÉPONSE DU TUTEUR : {answer}

1. claims : découpe la réponse du tuteur en affirmations factuelles simples (ignore les citations
   [p. N] et les formules de politesse). Pour chacune, supported = true seulement si les extraits
   l'affirment ou l'impliquent directement. Une définition ou un exemple absent des extraits
   n'est PAS supporté, même s'il est vrai dans la réalité.
2. answers_question : la réponse traite-t-elle la question posée ? (oui / partiellement / non)
3. matches_reference : la réponse est-elle cohérente avec la réponse de référence ? (oui / partiellement / non)"""


def light_judge(judge: LLM, sample: dict) -> dict:
    """faithfulness = part des affirmations supportées par le contexte (comme RAGAS) ;
    answer_relevancy / answer_correctness = verdicts oui/partiellement/non → 1 / 0.5 / 0."""
    try:
        j = judge.structured(
            "Tu es un évaluateur rigoureux. Réponds en JSON.",
            LIGHT_JUDGE_PROMPT.format(
                context="\n\n".join(sample["contexts"]), question=sample["question"],
                reference=sample["reference"], answer=sample["answer"]),
            LightJudgement,
        )
    except Exception as e:  # quota épuisé... : on réessaiera au prochain lancement
        print(f"  ! juge indisponible pour {sample['id']} ({type(e).__name__})")
        return {}
    return {
        "faithfulness": sum(c.supported for c in j.claims) / len(j.claims) if j.claims else None,
        "answer_relevancy": _GRADE[j.answers_question],
        "answer_correctness": _GRADE[j.matches_reference],
        "unsupported_claims": [c.claim for c in j.claims if not c.supported],
    }


# ---------- RAGAS ----------

def ragas_scores(samples: list[dict], settings: Settings, metric_names: list[str]) -> list[dict]:
    """samples : dicts {question, answer, contexts, reference}. Renvoie les scores par échantillon
    (None quand le juge a échoué, ex. quota épuisé)."""
    from langchain_core.embeddings import Embeddings
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy

    available = {
        "faithfulness": Faithfulness,
        "answer_relevancy": lambda: ResponseRelevancy(strictness=1),  # Groq refuse n>1
        "context_recall": LLMContextRecall,
        "llm_context_precision_with_reference": LLMContextPrecisionWithReference,
    }
    metrics = [available[n]() for n in metric_names]
    store = VectorStore(settings)

    class E5Embeddings(Embeddings):  # réutilise notre modèle d'embedding
        def embed_documents(self, texts):
            return store._embed(texts, "passage")

        def embed_query(self, text):
            return store._embed([text], "query")[0]

    judge = ChatOpenAI(
        **settings.judge,
        temperature=0,
        max_retries=8,
        reasoning_effort="low",
    )
    dataset = EvaluationDataset.from_list([
        {"user_input": s["question"], "response": s["answer"],
         "retrieved_contexts": s["contexts"], "reference": s["reference"]}
        for s in samples
    ])
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=LangchainLLMWrapper(judge),
        embeddings=LangchainEmbeddingsWrapper(E5Embeddings()),
        run_config=RunConfig(max_workers=2, timeout=300, max_retries=10, max_wait=90),
        raise_exceptions=False,
        show_progress=True,
    )
    df = result.to_pandas()
    return [{n: (None if np.isnan(row[n]) else float(row[n])) for n in metric_names} for _, row in df.iterrows()]


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.mean(vals) if vals else None


# ---------- Orchestration ----------

class RunDir:
    """Cache des étapes d'une expérience : eval/runs/<label>/<étape>.json"""

    def __init__(self, label: str):
        self.path = EVAL_DIR / "runs" / label
        self.path.mkdir(parents=True, exist_ok=True)

    def load(self, name: str):
        f = self.path / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def save(self, name: str, value) -> None:
        (self.path / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def stage(self, name: str, fn: Callable):
        value = self.load(name)
        if value is None:
            print(f"· {name}")
            value = fn()
            self.save(name, value)
        else:
            print(f"· {name} (déjà calculé)")
        return value


def run(
    label: str = "",
    prompt_version: int | None = None,
    judge_mode: Literal["leger", "ragas"] = "leger",
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    search_mode: str | None = None,
) -> dict:
    """judge_mode='leger' : 1 appel juge par réponse (tient dans les quotas gratuits) ;
    judge_mode='ragas' : métriques RAGAS officielles (≈3 appels juge par réponse)."""
    settings = get_settings()
    if prompt_version is not None:
        settings.prompt_version = prompt_version
    if search_mode is not None:
        settings.search_mode = search_mode
    store = VectorStore(settings)
    tutor = Tutor(store=store)
    judge = LLM(settings, **settings.judge, temperature=0)
    judge_slug = re.sub(r"[^A-Za-z0-9.-]+", "-", settings.judge["model"])

    prompts = [load_prompt(n).tag for n in ("answer", "quiz", "remediation")] + [styles_tag()]
    # Numéro du snapshot = plus haute version présente (answer@v3 + styles@v4 -> prompts-v4).
    snapshot = max(int(tag.rsplit("@v", 1)[1]) for tag in prompts)
    label = label or f"prompts-v{snapshot}" + (
        "" if settings.search_mode == "dense" else f"-{settings.search_mode}")
    rd = RunDir(label)
    # Ce qui détermine les réponses générées : si ça change, le cache n'est plus valable.
    config = {"label": label, "generator": settings.llm_model, "prompts": prompts, "top_k": settings.top_k,
              "search_mode": settings.search_mode}
    previous = rd.load("config")
    if previous:
        previous = {"search_mode": "dense", **previous}  # les premiers runs étaient tous en dense
    if previous and {k: previous.get(k) for k in config} != config:
        raise RuntimeError(f"eval/runs/{label} a été produit avec une autre configuration : {previous}. "
                           "Changez de --label ou supprimez ce dossier.")
    rd.save("config", {**config, "started": (previous or {}).get("started") or datetime.now().isoformat(timespec="seconds")})

    refs = load_jsonl(EVAL_DIR / "reference.jsonl")
    in_scope = [r for r in refs if r["source"]]
    report: dict = {**config, "judge": settings.judge["model"], "judge_mode": judge_mode,
                    "date": datetime.now().isoformat(timespec="seconds"), "summary": {}, "complete": True}

    report["summary"]["retrieval"] = rd.stage(
        "retrieval", lambda: retrieval_metrics(store, in_scope, settings.top_k))
    # Questions reformulées avec peu de mots du cours : teste la robustesse aux formulations d'élèves.
    report["summary"]["retrieval_paraphrases"] = rd.stage(
        "retrieval_paraphrases",
        lambda: retrieval_metrics(store, load_jsonl(EVAL_DIR / "paraphrases.jsonl"), settings.top_k))

    for level in READING_LEVELS:
        def answer_all(level=level):
            # Sauvegarde après chaque réponse : un quota épuisé en cours de route ne perd rien.
            partial = rd.load(f"answers_{level}.partial") or {}
            for r in refs:
                if r["id"] not in partial:
                    ans = tutor.ask(r["question"], reading_level=level)
                    partial[r["id"]] = {**r, "answer": ans.text, "raw_answer": ans.raw_text,
                                        "contexts": ans.contexts, "context_pages": ans.context_pages}
                    rd.save(f"answers_{level}.partial", partial)
            return [partial[r["id"]] for r in refs]

        rows = rd.stage(f"answers_{level}", answer_all)
        rows = [{**row, **readability(row["answer"])} for row in rows]  # recalcul : sans LLM, toujours à jour
        scoped = [row for row in rows if row["source"]]
        out = [row for row in rows if not row["source"]]

        # Scores du juge : cache par juge, on ne recalcule que ce qui manque.
        if judge_mode == "leger":
            names = list(LIGHT_METRICS)
        else:
            names = [m for m in metrics if level == "standard" or m not in CONTEXT_METRICS]
        cache_name = f"{judge_mode}-{judge_slug}_{level}"
        cached = rd.load(cache_name) or {}
        todo = [row for row in scoped if not cached.get(row["id"]) or
                any(n not in cached[row["id"]] for n in names)]
        if todo:
            print(f"· {cache_name} ({len(todo)} réponses à juger)")
            if judge_mode == "leger":
                for row in todo:
                    if scores := light_judge(judge, row):
                        cached[row["id"]] = scores
                        rd.save(cache_name, cached)  # sauvegarde au fil de l'eau
            else:
                for row, sc in zip(todo, ragas_scores(todo, settings, names)):
                    cached[row["id"]] = {**cached.get(row["id"], {}), **{k: v for k, v in sc.items() if v is not None}}
                rd.save(cache_name, cached)
        else:
            print(f"· {cache_name} (déjà calculé)")

        refusal_name = f"refusal-{judge_slug}_{level}"
        refusals = rd.load(refusal_name) or {}
        for row in out:
            if refusals.get(row["id"]) is None:
                refusals[row["id"]] = judge_refusal(judge, row["question"], row["answer"])
        rd.save(refusal_name, refusals)

        summary = {n: _mean(cached.get(row["id"], {}).get(n) for row in scoped) for n in names}
        summary.update(citation_metrics(store, scoped))
        missing = sum(n not in cached.get(row["id"], {}) for row in scoped for n in names)
        missing += sum(v is None for v in refusals.values())
        summary["words_mean"] = statistics.mean(row["words"] for row in scoped)
        summary["words_per_sentence_mean"] = statistics.mean(row["words_per_sentence"] for row in scoped)
        summary["kandel_moles_mean"] = statistics.mean(row["kandel_moles"] for row in scoped)
        summary["refusal_rate_out_of_scope"] = _mean(refusals.values())
        report["summary"][level] = summary
        if missing:
            report["complete"] = False
            print(f"  ! {missing} scores manquants en mode {level} : relancer la même commande plus tard")

    rem = rd.stage("remediation", lambda: remediation_rows(
        tutor, load_jsonl(EVAL_DIR / "remediation.jsonl"), "simplifie"))
    sims = [r["similarity"] for r in rem]
    report["summary"]["remediation"] = {
        "exercise_similarity_mean": statistics.mean(sims),
        "exercise_near_duplicate_rate": statistics.mean(s > 0.92 for s in sims),
        "explanation_words_mean": statistics.mean(readability(r["explanation"])["words"] for r in rem),
    }

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}-{judge_mode}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["path"] = str(path)
    return report


def format_summary(report: dict) -> str:
    lines = [f"# Évaluation {report['label']} (juge {report['judge_mode']}) — {report['date']}"
             + ("" if report["complete"] else "  (INCOMPLÈTE)"),
             f"générateur={report['generator']}  juge={report['judge']}  prompts={', '.join(report['prompts'])}", ""]
    for section, values in report["summary"].items():
        lines.append(f"## {section}")
        for k, v in values.items():
            lines.append(f"  {k:<32} {'—' if v is None else f'{v:.3f}'}")
    return "\n".join(lines)


def compare(path_a: Path, path_b: Path) -> str:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (path_a, path_b))
    lines = [f"{'métrique':<45} {a['label']:>12} {b['label']:>12}   Δ"]
    for section in a["summary"]:
        for k, va in a["summary"][section].items():
            vb = b["summary"].get(section, {}).get(k)
            if va is None or vb is None:
                continue
            lines.append(f"{section + '.' + k:<45} {va:>12.3f} {vb:>12.3f}   {vb - va:+.3f}")
    return "\n".join(lines)
