# Brancher le vrai pipeline RAG dans l'orchestration `mlops`

Le pipeline RAG de la branche `mlops` (`orchestration/tuteur_pipelines/rag_pipeline.py`) est
simulé : découpage en mots, faux embeddings (sha256), faux quiz. Le module `tuteur.pipeline`
de cette branche fait les mêmes étapes avec le vrai code du tuteur, et produit les mêmes
fichiers et le même manifeste `registry/rag/latest.json`.

| Étape (tâche Airflow) | Simulé (`mlops`) | Réel (`tuteur.pipeline`) |
| --- | --- | --- |
| `load_course` | `inputs/course_demo.txt` | tous les PDF / MD / TXT de `inputs/` → `01_sources.json` |
| `clean_content` | espaces normalisés | texte page par page, PyMuPDF → `02_pages.json` |
| `chunk_content` | 320 caractères, sans chevauchement | 800 caractères, chevauchement 150, page gardée → `03_chunks.json` |
| `create_embeddings` | sha256, 12 dimensions | `multilingual-e5-small`, 384 dimensions → `04_embeddings.json` |
| `index_vectors` | JSON | ChromaDB (cosinus) + BM25 → `05_vector_index.json` + `chroma/` |
| `generate_quiz` | 3 consignes fixes | `Tutor.quiz` : LLM, JSON vérifié par Pydantic, un quiz par document → `06_quiz.json` |
| `evaluate_quiz` | score synthétique | pages citées valides + recherche sur `reference.jsonl` → `07_evaluation.json` |
| `register_in_mlflow` | paramètres mock | vrais paramètres (modèles, découpage, prompts) + manifeste, `is_simulated: false` |

## 1. Installer le package dans l'image Airflow

Dans `orchestration/requirements-airflow.txt`, ajouter (PyTorch CPU d'abord : environ 2 Go de moins) :

```text
--extra-index-url https://download.pytorch.org/whl/cpu
torch
tuteur @ git+https://github.com/Nour-Ghribi/Tuteur_-ducatif_inclusif.git@genai-rag
```

Le package fonctionne en Python 3.12 (image `apache/airflow:3.3.2-python3.12`).

## 2. Remplacer le DAG

Copier `integration/airflow/rag_pipeline.py` à la place de `orchestration/dags/rag_pipeline_demo.py`
(même `dag_id`, mêmes tâches : supprimer l'ancien fichier, sinon Airflow voit deux DAG du même nom).

## 3. Variables d'environnement (`x-airflow-common` de `compose.yaml`)

| Variable | Rôle | Exemple |
| --- | --- | --- |
| `LLM_BASE_URL` | API compatible OpenAI | `https://api.groq.com/openai/v1` |
| `LLM_MODEL` | générateur | `openai/gpt-oss-120b` |
| `LLM_API_KEY` | clé, à mettre dans `.env`, jamais dans Git | `${LLM_API_KEY}` |
| `RAG_QUIZ_QUESTIONS` | questions par document (optionnel) | `5` |
| `RAG_READING_LEVEL` | `standard` ou `simplifie` (optionnel) | `standard` |

Le modèle d'embedding est téléchargé au premier run (environ 470 Mo) : monter un volume sur
`/home/airflow/.cache/huggingface` évite de le retélécharger.

## 4. Données d'entrée

Dans `orchestration/shared/inputs/` : les cours (PDF, MD ou TXT) et, pour mesurer la recherche,
`reference.jsonl` (copie de `eval/reference.jsonl` de cette branche). Sans `reference.jsonl`, le
score repose seulement sur les pages citées par le quiz.

## 5. Correctif de deux lignes dans `evaluation_pipeline.py`

L'évaluation `mlops` lit `synthetic_quality_score` et n'accepte qu'une évaluation marquée
synthétique. Le vrai pipeline ne prétend pas être synthétique : il écrit `quality_score` et
`is_synthetic_evaluation: false`. Dans `verify_evaluation_results` :

```python
        score_key = "synthetic_quality_score" if pipeline == "rag" else "synthetic_policy_score"
        if pipeline == "rag" and "quality_score" in metrics:   # ajout 1 : score du vrai pipeline
            score_key = "quality_score"
        results[pipeline] = {
            **checks[pipeline],
            "score_name": score_key,
            "score": metrics.get(score_key),
            "evaluation_is_synthetic": metrics.get("is_synthetic_evaluation") is True
            or manifest.get("is_simulated") is False,          # ajout 2 : accepte un run réel
        }
```

Le pipeline simulé continue de fonctionner (il n'a pas `quality_score`, et son manifeste a
`is_simulated: true`).

**Vérifié** le 4 novembre 2026 en exécutant le code `evaluation_pipeline.py` de la branche `mlops`
sur un manifeste produit par `tuteur.pipeline` (cours de photosynthèse) :

| | Décision RAG |
| --- | --- |
| Sans le correctif | refusé (score introuvable) |
| Avec le correctif | accepté : `quality_score` 1.0, seuil 0.75 |

## 6. Le score de qualité

`quality_score` = moyenne de :

- `source_page_rate` : part des questions dont les pages citées font partie des pages du quiz ;
- `retrieval_hit_at_5` : part des questions de `reference.jsonl` (limitées aux cours indexés)
  dont le bon passage arrive dans les 5 premiers résultats de la recherche hybride.

Ces mesures n'appellent pas de LLM : le batch reste rapide et ne consomme pas de quota. La
fidélité au cours (LLM juge) se mesure avec `tuteur eval` (v5 : 1.00 en standard et en FALC).

## 7. Tester sans Airflow ni LLM

```bash
pytest tests/test_pipeline.py
```

Le test exécute toutes les étapes sur le cours de photosynthèse, avec un LLM et un MLflow simulés.
