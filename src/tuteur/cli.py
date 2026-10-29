"""Ligne de commande : tuteur ingest | docs | search | ask | quiz | remediate"""

import argparse
import json
import sys
from pathlib import Path

from tuteur.config import get_settings


def _parse_pages(spec: str) -> list[int]:
    """'3' -> [3] ; '2-5' -> [2,3,4,5] ; '1,4,7' -> [1,4,7]"""
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = map(int, part.split("-"))
            pages.extend(range(a, b + 1))
        else:
            pages.append(int(part))
    return pages


def cmd_ingest(args):
    from tuteur.chunking import chunk_document
    from tuteur.ingestion import load_document
    from tuteur.vectorstore import VectorStore

    s = get_settings()
    store = VectorStore(s)
    for path in args.paths:
        doc = load_document(Path(path), images_dir=s.images_dir)
        chunks = chunk_document(doc, s.chunk_size, s.chunk_overlap)
        store.add(chunks)
        n_img = sum(len(p.images) for p in doc.pages)
        print(f"✓ {doc.source} (doc_id={doc.doc_id}) : {len(doc.pages)} pages, {len(chunks)} chunks, {n_img} images")


def cmd_docs(args):
    from tuteur.vectorstore import VectorStore

    for doc_id, source in VectorStore().documents().items():
        print(f"{doc_id}  {source}")


def cmd_search(args):
    from tuteur.vectorstore import VectorStore

    for r in VectorStore().search(args.query, k=args.k, mode=args.recherche):
        print(f"--- score={r.score:.3f}  {r.metadata['source']} p.{r.metadata['page']}")
        print(r.text[:400])


def cmd_ask(args):
    from tuteur.generation import Tutor

    ans = Tutor().ask(args.question, reading_level=args.niveau)
    print(ans.text)
    print("\nSources :", ", ".join(f"p.{s['page']} ({s['score']})" for s in ans.sources))
    if ans.invalid_citations:
        print(f"(citations retirées car hors des passages fournis : p. {', '.join(map(str, ans.invalid_citations))})")


def cmd_quiz(args):
    from tuteur.generation import Tutor

    quiz = Tutor().quiz(
        topic=args.topic,
        doc_id=args.doc,
        pages=_parse_pages(args.pages) if args.pages else None,
        n=args.n,
        difficulty=args.difficulte,
        reading_level=args.niveau,
    )
    out = quiz.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"✓ {len(quiz.items)} questions écrites dans {args.out}")
    else:
        print(out)


def cmd_remediate(args):
    from tuteur.generation import Tutor

    rem = Tutor().remediate(args.question, args.reponse_eleve, args.bonne_reponse, reading_level=args.niveau)
    print(rem.model_dump_json(indent=2))


def cmd_eval(args):
    from tuteur.evaluation import DEFAULT_METRICS, compare, format_summary, run

    if args.compare:
        print(compare(*args.compare))
        return
    metrics = DEFAULT_METRICS + (("llm_context_precision_with_reference",) if args.complet else ())
    report = run(label=args.label, prompt_version=args.prompts, judge_mode=args.juge, metrics=metrics,
                 search_mode=args.recherche)
    print(format_summary(report))
    print(f"\n✓ Résultats détaillés : {report['path']}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # accents dans la console Windows

    p = argparse.ArgumentParser(prog="tuteur", description="Tuteur éducatif inclusif — GenAI + RAG")
    sub = p.add_subparsers(required=True)

    sp = sub.add_parser("ingest", help="Indexer un ou plusieurs cours (PDF/TXT/MD)")
    sp.add_argument("paths", nargs="+")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("docs", help="Lister les documents indexés")
    sp.set_defaults(func=cmd_docs)

    sp = sub.add_parser("search", help="Recherche sémantique (sans LLM)")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=5)
    sp.add_argument("--recherche", choices=["dense", "hybride"], help="mode de recherche (défaut : SEARCH_MODE)")
    sp.set_defaults(func=cmd_search)

    niveau = dict(choices=["standard", "simplifie"], default="standard", help="niveau de lecture (inclusion)")

    sp = sub.add_parser("ask", help="Poser une question sur le cours")
    sp.add_argument("question")
    sp.add_argument("--niveau", **niveau)
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("quiz", help="Générer un quiz")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic", help="thème (recherche sémantique)")
    g.add_argument("--doc", help="doc_id (voir `tuteur docs`), avec --pages")
    sp.add_argument("--pages", help="ex. 3-5 ou 1,4")
    sp.add_argument("-n", type=int, default=5)
    sp.add_argument("--difficulte", choices=["facile", "moyen", "difficile"], default="moyen")
    sp.add_argument("--niveau", **niveau)
    sp.add_argument("-o", "--out", help="fichier JSON de sortie")
    sp.set_defaults(func=cmd_quiz)

    sp = sub.add_parser("remediate", help="Reprise après une mauvaise réponse")
    sp.add_argument("question")
    sp.add_argument("reponse_eleve")
    sp.add_argument("bonne_reponse")
    sp.add_argument("--niveau", **niveau)
    sp.set_defaults(func=cmd_remediate)

    sp = sub.add_parser("eval", help="Évaluer le tuteur sur eval/reference.jsonl (RAGAS + métriques maison)")
    sp.add_argument("--label", default="", help="nom de l'expérience (défaut : prompts-vN) ; relancer reprend le run")
    sp.add_argument("--prompts", type=int, help="version des prompts à évaluer (défaut : la dernière)")
    sp.add_argument("--recherche", choices=["dense", "hybride"], help="mode de recherche (défaut : SEARCH_MODE)")
    sp.add_argument("--juge", choices=["leger", "ragas"], default="leger",
                    help="leger : 1 appel juge par réponse (quotas gratuits) ; ragas : métriques RAGAS (≈3 appels)")
    sp.add_argument("--complet", action="store_true",
                    help="avec --juge ragas : ajoute context precision (≈5 appels juge par question)")
    sp.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"), help="comparer deux résultats")
    sp.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    if getattr(args, "doc", None) and not args.pages:
        p.error("--doc nécessite --pages")
    args.func(args)


if __name__ == "__main__":
    main()
