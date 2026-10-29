# Tuteur éducatif inclusif — module GenAI + RAG

Premier module du projet : transformer un cours (PDF, TXT, MD) en base RAG, puis générer
réponses, quiz et remédiations adaptés — avec un niveau de lecture **simplifié (FALC)** pour l'inclusion.

```
Cours (PDF/texte) ──► ingestion.py ──► chunking.py ──► vectorstore.py ──► generation.py ──► Quiz / Réponse / Remédiation
                      texte + images    passages       embeddings E5      prompts YAML        (JSON validé Pydantic)
                                        + n° de page   + ChromaDB         + LLM
```

| Fichier | Rôle |
|---|---|
| `src/tuteur/ingestion.py` | Extraction texte + images par page (PyMuPDF). Images → `data/images/` (pour le futur module Inclusion). |
| `src/tuteur/chunking.py` | Découpage par paragraphes/phrases avec chevauchement ; chaque chunk garde sa page. |
| `src/tuteur/vectorstore.py` | Embeddings `multilingual-e5-small` (bon en français, tourne sur CPU) + ChromaDB persistant. |
| `src/tuteur/llm.py` | Client unique pour **toute API compatible OpenAI** (Ollama, Groq, Gemini, OpenAI). Sortie JSON validée + 1 relance si invalide. Trace latence/tokens (→ MLflow plus tard). |
| `src/tuteur/prompts/*.yaml` | Prompts **versionnés** (`name@vN`) — exigence MLOps du sujet. |
| `src/tuteur/schemas.py` | Formats Quiz / QuizItem / Remédiation, avec règles (QCM = 4 choix, réponse ∈ choix…). |
| `src/tuteur/generation.py` | `Tutor.ask()`, `Tutor.quiz()`, `Tutor.remediate()`. |
| `src/tuteur/cli.py` | Commande `tuteur`. |

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac : source .venv/bin/activate)
pip install -e ".[dev]"
copy .env.example .env          # puis choisir le LLM dans .env
```

> **Windows :** si le chemin du projet est très long, `chromadb` échoue avec « DLL load failed … filename too long ».
> Créer alors le venv dans un chemin court (`python -m venv C:\Users\<moi>\.venvs\tuteur`).
> Pour économiser ~2 Go : `pip install torch --index-url https://download.pytorch.org/whl/cpu` avant le reste.

**Choix du LLM** (dans `.env`) — tout passe par l'API compatible OpenAI, on change juste 3 variables :
- **Ollama** (local, gratuit) : installer depuis ollama.com puis `ollama pull qwen2.5:7b` (tient dans 8 Go de VRAM).
- **Groq** ou **Gemini** : clé API gratuite, aucun GPU nécessaire.

## Utilisation

```bash
tuteur ingest data/raw/photosynthese.md mon_cours.pdf   # indexer
tuteur docs                                              # lister (doc_id)
tuteur search "pourquoi les feuilles sont vertes"        # tester le retrieval, sans LLM
tuteur ask "C'est quoi la chlorophylle ?" --niveau simplifie
tuteur quiz --topic "photosynthèse" -n 5 --difficulte facile -o quiz.json
tuteur quiz --doc <doc_id> --pages 3-5 -n 8             # quiz sur un chapitre
tuteur remediate "Que rejette la photosynthèse ?" "du CO2" "du dioxygène"
```

## Tests

```bash
pytest
```
Les tests n'ont pas besoin de LLM : le retrieval est testé avec le vrai modèle d'embedding,
la génération avec un LLM simulé.

## Évaluation

Jeu de référence : `eval/reference.jsonl` (16 questions + 2 hors cours) et `eval/remediation.jsonl` (4 erreurs d'élève).

```bash
tuteur eval --prompts 1                 # évalue les prompts v1 (juge léger par défaut)
tuteur eval --prompts 2
tuteur eval --compare eval/results/prompts-v1-leger.json eval/results/prompts-v2-leger.json
tuteur eval --juge ragas                # métriques RAGAS officielles (≈3 appels juge / réponse)
```

- **Juge léger** (défaut) : 1 appel par réponse, critères RAGAS (part des affirmations supportées
  par le contexte, pertinence, exactitude vs référence). Tient dans les quotas gratuits Groq.
- **Juge** configurable à part (`EVAL_JUDGE_*` dans `.env`) : on utilise `qwen/qwen3.8-27b`,
  d'une autre famille que le générateur `gpt-oss-120b` (limite l'auto-complaisance du juge).
- Chaque étape est mise en cache dans `eval/runs/<label>/` : relancer reprend là où ça s'est arrêté.
- Prompts versionnés : `src/tuteur/prompts/<nom>.v<N>.yaml` ; `PROMPT_VERSION` ou `--prompts` pour figer une version.

**Résultats v1 → v2** (générateur gpt-oss-120b, juge qwen3.8-27b, 26/10/2026) :

| | v1 | v2 |
|---|---|---|
| Fidélité au cours — standard | 0.93 | **0.99** |
| Fidélité au cours — simplifié (FALC) | 0.70 | **0.95** |
| Longueur moyenne — simplifié | 144 mots | **38 mots** |
| Mots par phrase — simplifié | 9.8 | **7.3** |
| Refus des questions hors cours | 100 % | 100 % |
| Exercices de remédiation quasi identiques à la question | 50 % | 25 % |
| Retrieval hit@1 / hit@5 | 0.56 / 0.94 | 0.56 / 0.94 |

### Recherche dense vs hybride (BM25 + embeddings, fusion RRF)

`SEARCH_MODE=hybride` (défaut) ou `dense` ; `tuteur search "..." --recherche dense` pour comparer.
`eval/paraphrases.jsonl` : 10 questions reformulées avec peu de mots du cours (comme un élève),
pour vérifier que BM25 n'avantage pas seulement les questions écrites avec le vocabulaire du cours.

| | dense | hybride |
|---|---|---|
| hit@1 — questions de référence (16) | 0.56 | **0.75** |
| hit@5 — questions de référence | 0.94 | **1.00** |
| hit@1 — questions reformulées (10) | **0.80** | 0.70 |
| hit@5 — questions reformulées | 1.00 | 1.00 |
| Mode standard (prompts v2) : fidélité / pertinence / exactitude | 0.99 / 0.94 / 0.94 | **1.00 / 1.00 / 1.00** |

Le LLM reçoit les 5 premiers passages : c'est hit@5 qui compte le plus, et seul l'hybride atteint 1.0
partout. La question « combien de quiz par chapitre » (passage p. 4 au rang 6 en dense) est maintenant résolue.
Mode simplifié en hybride : pas encore évalué (quota journalier Groq atteint).

### Citations

Problème observé : « [p. 8] » pour un PDF de 4 pages (le numéro de section « 8. Valeur ajoutée » pris
pour une page), et des pages citées qui ne contiennent pas l'information.

- **Garde-fou** (`src/tuteur/citations.py`) : toute page citée qui n'est pas celle d'un passage fourni
  est retirée avant affichage ; `tuteur ask` signale les citations retirées.
- **Prompt `answer.v3`** : chaque passage a un en-tête `=== PASSAGE i — page N ===` séparé du texte,
  et la consigne précise que les numéros présents dans le texte ne sont jamais des pages.
- **Métriques** (sur la réponse brute, avant garde-fou) : `citation_rate`, `citation_validity`
  (page citée ∈ passages fournis), `citation_hit_pdf` (la page citée contient l'information — PDF seulement).

| Recherche hybride | v2 | v3 |
|---|---|---|
| Citations valides — standard / simplifié | 0.95 / 0.97 | **1.00 / 1.00** |
| Bonne page citée (PDF) — standard / simplifié | 0.83 / 0.67 | 0.83 / **1.00** |
| Fidélité — standard / simplifié | 1.00 / 0.83 | 0.99 / **0.90** |

Attention au bruit : avec 16 questions et une génération à température 0.3, deux runs du **même**
prompt varient (ex. remédiation : 25 % → 0 % de quasi-doublons alors que son prompt n'a pas changé).
Seuls les écarts nets et cohérents sont à interpréter.

### Mode simplifié sans exemples inventés (snapshot v4)

La consigne « termine par un exemple concret » (styles v2) poussait le modèle à inventer des exemples
hors cours (« une vache mange de l'herbe et reçoit du dioxygène »). `styles.v4` : simplifier = dire la
même chose avec des mots plus simples ; un exemple seulement s'il est dans le cours.
`--prompts 4` = answer v3 + styles v4 (le label d'un run suit le numéro de snapshot).

| Recherche hybride, mode simplifié | v3 | v4 |
|---|---|---|
| Fidélité au cours | 0.90 | **1.00** |
| Affirmations non supportées (16 questions) | 7 | **0** |
| Pertinence / exactitude | 1.00 / 1.00 | 0.97 / 0.97 |
| Longueur moyenne | 34 mots | **20 mots** |
| Mots par phrase / score Kandel-Moles | 6.8 / 83 | 9.1 / 77 |

Contrepartie : en reprenant les phrases du cours, les phrases s'allongent un peu (toujours sous la
limite de 12 mots). Une réponse est jugée partielle : « pourquoi la photosynthèse est importante pour
les animaux » répond dioxygène mais oublie les chaînes alimentaires.

**Snapshot v5** (`styles.v5` : « simplifier, ce n'est pas couper », donner tous les éléments du cours) :
pertinence / exactitude simplifié 0.97 → **1.00**, fidélité toujours 1.00, 19 mots en moyenne.
photo-09 répond maintenant dioxygène **et** nourriture des herbivores puis des carnivores.
La « bonne page (PDF) » baisse (standard 1.00 → 0.67) alors que le prompt standard n'a pas changé :
c'est du bruit (6 questions PDF), comme la remédiation (0 % → 25 % de quasi-doublons, prompt identique).

## Prochaines étapes (GenAI / RAG)

1. **Jeu de test** : passer de 16 à ~50 questions pour que les écarts de 1 question ne pèsent plus 6 %.
2. **Remédiation** : la similarité d'embeddings capte mal « un autre angle » ; ajouter un critère au juge.
3. **MLflow** : logger chaque `eval/results/*.json` (params = prompts/modèles, metrics = scores).
4. **Mini-jeux** : ajouter un prompt + schéma (ex. « associer les paires », « texte à trous »).
5. **Multimodal / Inclusion** : décrire les images de `data/images/` (BLIP/LLaVA) et indexer
   ces descriptions comme chunks → le RAG « voit » les schémas.
6. **API** : exposer `Tutor` via FastAPI (le module RL appellera `quiz(difficulty=...)`).


---

## Couche agentique : orchestration temps réel + interface (branche `agentic-orchestration-ui`)

Le module ci-dessus est une **bibliothèque** (`Tutor.ask/quiz/remediate`). Cette couche en fait **l'application** :
elle déroule la session d'apprentissage complète et l'affiche de façon accessible.

```
élève ─► interface React (frontend/) ─► routeur FastAPI ─► graphe LangGraph (backend/agentic/)
                                                              ├─ Tutor GenAI + RAG (ce module, en processus)
                                                              ├─ service RL (adaptateur HTTP, simulé en attendant)
                                                              └─ données d'apprentissage (agrégats, simulées en attendant)
```

| Ce que la couche ajoute | Où |
|---|---|
| comprendre la demande (« flashcards », « étape par étape »…) et choisir le format | `backend/agentic/src/tutor_agentic/routing/` |
| carte mentale, étapes, comparaison, notions clés (prompts versionnés) | `…/genai_ext/` |
| correction (corrigés gardés côté serveur), historique, remédiation → RL | `…/graph/`, `…/service.py`, `…/history.py` |
| vérification des pages sources, reprises bornées, mode dégradé | `…/graph/verification.py`, `…/integrations/` |
| descriptions de figures et adaptation des couleurs (daltonisme) | `…/integrations/inclusion_local.py`, `…/inclusion/` |
| interface React/TypeScript : 17 composants validés, accessibilité, préférences déclarées | `frontend/` |

- Lancer la démo (services simulés, sans clé API) : [`backend/agentic/README.md`](backend/agentic/README.md), [`frontend/README.md`](frontend/README.md).
- Contrats et demandes à chaque équipe : [`docs/agentic/INTEGRATION.md`](docs/agentic/INTEGRATION.md).
- Rapport (PDF) : [`docs/agentic/Rapport_Couche_Agentique.pdf`](docs/agentic/Rapport_Couche_Agentique.pdf).
- Tests : `cd backend/agentic && pytest` · `cd frontend && npm test`. Tout tourne sans réseau ni LLM ; les résultats simulés sont étiquetés comme tels.
