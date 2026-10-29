# Intégration de la couche agentique — contrats et points à valider

Branche `agentic-orchestration-ui`. Ce document sert de **base de discussion avec l'équipe** : ce que la
couche consomme, ce qu'elle attend de chacun, et les fichiers partagés qu'elle touche.

## 1. Répartition (rappel)

| Rôle | Possède | La couche agentique… |
|---|---|---|
| E1 RAG | ingestion, chunking, index, retrieval | appelle `Tutor.store.search` ; ne réimplémente rien |
| E2 GenAI | prompts, quiz, remédiation, évaluation | appelle `Tutor.ask/quiz/remediate` ; ajoute 4 formats via `Tutor.llm.structured` |
| E3 RL | politique, entraînement | appelle `POST /v1/recommend` et envoie les résultats ; n'entraîne rien |
| E5 MLOps | FastAPI, Docker, MLflow, Airflow, Prometheus, CI | fournit un routeur montable et des événements de télémétrie ; ne déploie rien |
| E4 (cette couche) | orchestration, session d'apprentissage, inclusion, interface | — |

## 2. Module GenAI + RAG (appelé en processus : `TUTOR_GENAI_BACKEND=tuteur`)

Ce que la couche **utilise** (si ces signatures changent, `integrations/tuteur_backend.py` est le seul fichier à adapter) :

| Appel | Usage | Champs relus |
|---|---|---|
| `Tutor.store.search(query, k, where={"doc_id": …})` | retrieval | `id`, `text`, `metadata.{doc_id,page,has_images}`, `score` |
| `Tutor.quiz(topic, n, difficulty, types, reading_level)` | quiz et flashcards | `items[].{type,question,choices,answer,explanation,difficulty,competence,source_pages}` |
| `Tutor.ask(question, reading_level)` | explication | `text`, `context_pages`, `invalid_citations`, `prompt` |
| `Tutor.remediate(question, student_answer, correct_answer, history, reading_level)` | reprise après échec | `diagnostic`, `explanation`, `exercise` |
| `Tutor.llm.structured(system, user, schema)` | formats ajoutés, correction libre, intention | sortie validée Pydantic |

Conversions : `qcm`→QCM (options a–d), `vrai_faux`→vrai/faux, `flashcard`→carte, ou réponse libre quand c'est
un exercice de remédiation ; `facile/moyen/difficile` ↔ `easy/medium/hard`.

**Demandes à l'équipe GenAI/RAG**

1. `doc_id` en paramètre de `ask()` et `quiz(topic=…)` (aujourd'hui la recherche porte sur tout l'index → mélange possible de cours).
2. `quiz()` et `remediate()` renvoient les passages utilisés (comme `ask()`), pour vérifier les `source_pages`.
3. Un timeout configurable dans `LLM` (aujourd'hui 8 reprises et le délai par défaut du SDK, 10 min ; la couche le surcharge après construction).
4. `Remediation.diagnostic` : formuler comme **hypothèse** (la couche l'affiche déjà comme telle).
5. Accepter ou non les prompts ajoutés (`genai_ext/prompts/*.yaml`, même convention `nom.vN.yaml`) : s'ils sont repris dans `src/tuteur/prompts`, la couche pourra les supprimer.
6. Mini-jeux (README GenAI, « prochaines étapes » n°4) : toujours à faire côté GenAI ; le rendu est prêt à recevoir de nouveaux blocs.

## 3. Service RL (non disponible — adaptateur HTTP + simulation)

`POST /v1/recommend` : `{student_ref (pseudonyme), course_id, topic, features{recent_scores, avg_time_s, level, last_outcome, declared_needs}, available_activities[{activity_type, difficulty, topic}]}`
→ `{recommendation_id, activity_type, difficulty, topic, policy_version?, rationale?}`.
La couche **rejette** toute recommandation absente de `available_activities`.
`POST /v1/outcomes` : `{recommendation_id, student_ref, completed, score?, time_spent_s?}` → `{accepted}` (signal de récompense).
Types : `quiz|exercise|flashcards|explanation|revision|mini_game` ; difficultés `easy|medium|hard`.
À valider : le vocabulaire, et si l'équipe RL veut un catalogue d'activités réel plutôt que la grille par défaut.

## 4. Données d'apprentissage / rapports (propriétaire à confirmer : RL ou MLOps)

`POST /v1/learning-summaries` : `{class_id, course_id?, period_start, period_end}` → agrégats par notion
(`topic, attempts, success_rate, median_time_s, common_error_tags`) et `learner_count`. **Jamais de lignes par élève.**

## 5. MLOps (E5)

- **Monter** le routeur dans l'application FastAPI (extrait dans `backend/agentic/README.md`) ; ce dépôt ne crée pas d'application de production (`dev_server.py` = harnais local).
- `/health`, `/ready` (`service.readiness()` indique mock/tuteur/http par service), `/metrics` : à fournir côté application.
- **Télémétrie** : `Telemetry(sink)` avec un objet ayant `emit(event)` ; événements `tutor.adapter.call`, `tutor.verification.result`, `tutor.workflow.completed` (sans texte d'élève). Un pont MLflow Tracing / Prometheus est à écrire côté MLOps (≈ 20 lignes).
- **Docker** : variables dans `backend/agentic/.env.example` ; volumes `data/chroma` et `data/images` ; le frontend se construit avec `npm run build` (statique) et appelle `/api` en relatif.
- **CI** : `pytest` et `ruff check src tests` dans `backend/agentic` ; `npm ci && npm test && npm run build` dans `frontend`.
- **Airflow** : le schéma d'architecture montre un pipeline RAG à base de « mock embeddings / mock index ». Le vrai pipeline existe (`tuteur ingest`, `tuteur eval`) : l'appeler plutôt que de le simuler. Les manifestes `registry/validation/latest.json` ne sont pas encore consommés (aucun format défini) : à convenir.
- **Python** : testé en 3.13 ; aligner avec l'image Docker.
- **Authentification** : jeton de développement uniquement ; à remplacer par l'authentification de l'équipe via le protocole `Authenticator`.

## 6. Fichiers partagés modifiés par cette branche

| Fichier | Modification |
|---|---|
| `README.md` (racine) | section « Couche agentique » ajoutée **à la fin** ; le contenu GenAI/RAG n'est pas modifié |
| `.gitignore` (racine) | une ligne : `data/images_adapted/` (images générées) |

Tout le reste est nouveau : `backend/agentic/`, `frontend/`, `docs/agentic/`. Aucun fichier de `src/tuteur`, `eval`, `tests` ou `data` n'est touché.

## 7. Décisions à prendre en équipe

1. Qui possède l'inclusion (description d'images, daltonisme) : implémentée ici avec un modèle de vision compatible OpenAI et une adaptation sans modèle ; à valider.
2. Propriétaire du service de données d'apprentissage.
3. Où vit l'état (questions émises, historique) en production : mémoire de processus aujourd'hui ; Redis/base ensuite.
4. Cours multiples : un index par cours, ou `doc_id` dans l'API GenAI (demande n°1).
