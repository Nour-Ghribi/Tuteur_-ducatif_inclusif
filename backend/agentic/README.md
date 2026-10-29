# tutor-agentic — couche d'orchestration temps réel

Couche applicative du tuteur : elle **déroule une interaction d'apprentissage complète** en reliant le
module GenAI + RAG (`src/tuteur`), le futur service RL, les données d'apprentissage et l'interface.
Orchestration avec **LangGraph**, exposée comme **routeur FastAPI montable**.

> Ce que cette couche **n'est pas** : un second RAG, un second générateur ou une infrastructure MLOps.
> Elle appelle `Tutor` (retrieval, quiz, remédiation, réponses), n'entraîne aucun modèle et ne lance ni
> MLflow, ni Airflow, ni Prometheus. Airflow reste réservé aux traitements par lots.

## Ce qu'elle apporte (et que personne d'autre n'écrit)

| Besoin | Réalisation |
|---|---|
| Comprendre la demande (« flashcards », « étape par étape », « autre exercice »…) | `routing/` : règles FR/EN d'abord, classifieur LLM optionnel pour les cas ambigus |
| Formats absents du module GenAI (carte mentale, étapes, comparaison, notions clés) | `genai_ext/` : prompts YAML versionnés, appelés via `Tutor.llm.structured` |
| Corriger une réponse, **sans exposer les corrigés** | clés de réponse gardées côté serveur ; QCM corrigés localement, réponses libres notées par un LLM |
| Remédiation et recommandation | graphe : mauvaise réponse → `Tutor.remediate()` → RL ; historique de l'élève côté serveur |
| Distinguer constat et hypothèse | « erreur observée » ≠ « confusion probable » (formulation selon le nombre d'erreurs) |
| Vérifier avant d'afficher | structure, pages sources ⊆ passages récupérés, citations ; régénération bornée |
| Panne d'un service | dégradation prévisible : réponse partielle ou bloc de secours, jamais d'invention |
| Inclusion | descriptions de figures, adaptation des couleurs (daltonisme), préférences **déclarées** |
| Afficher | `UISpec` Pydantic validé (17 composants autorisés) → rendu React (`frontend/`) |

## Architecture

```
 React (frontend/)  ──HTTP──►  routeur FastAPI (api/)  ──►  TutorService (service.py)
                                   auth · erreurs               historique · clés de réponse · télémétrie
                                                                      │
                                                                      ▼
                                              ┌────────────── graphe LangGraph (graph/) ──────────────┐
  intake ─┬─ expérience ─► plan ─► retrieve ─► generate ◄──► verify (≤ 2 essais) ─► [recommend] ─┐
          ├─ réponse ────► évaluer ─► (faux) retrieve ─► generate(remédiation) ─► [recommend] ──┤
          ├─ parcours ───► recommend ──────────────────────────────────────────────────────────┤
          └─ rapport ────► données agrégées ─► generate(synthèse) ─────────────────────────────┤
                                                       attach_images ─► plan_ui ─► finalize ◄────┘
                                          toute erreur fatale ─► recover ─► finalize
                                                                      │
                          adaptateurs (integrations/)  ◄──────────────┘
   mock │ tuteur (module GenAI+RAG en processus) │ http (services des coéquipiers)
```

Un nœud n'est un « agent » que s'il décide : routage d'intention, boucle de vérification, reprise sur
erreur. Le reste (appels de services, correction QCM, mise en page) est déterministe.

## Démarrage

```bash
cd backend/agentic
py -3.13 -m venv .venv                       # Python ≥ 3.11
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest               # tests : aucun réseau, aucun modèle, données synthétiques
.venv/Scripts/ruff check src tests
```

**Démo locale (services simulés)** — deux terminaux :

```bash
# 1. backend (affiche deux jetons jetables : élève et enseignant)
.venv/Scripts/python -m tutor_agentic.dev_server          # http://127.0.0.1:8000
# 2. frontend
cd ../../frontend && npm install && npm run dev            # http://localhost:5173
```

**Avec le vrai module GenAI + RAG** (dans un venv à chemin court sous Windows, voir le README racine) :

```bash
pip install -e ../..            # module GenAI + RAG (chromadb, sentence-transformers…)
pip install -e ".[dev]"
tuteur ingest data/raw/photosynthese.md     # puis noter le doc_id : c'est le « cours » côté API
TUTOR_GENAI_BACKEND=tuteur python -m tutor_agentic.dev_server
```

`course_id` = `doc_id` du document indexé. Le LLM se règle dans le `.env` du module (`LLM_*`).

## Monter dans l'application FastAPI de l'équipe

```python
from tutor_agentic import TutorService
from tutor_agentic.api import create_tutor_router, install_error_handlers
from tutor_agentic.auth import build_authenticator
from tutor_agentic.config import get_settings

settings = get_settings()
service = TutorService.from_settings(settings)          # Telemetry(sink) en option
app.include_router(create_tutor_router(service, build_authenticator(settings)), prefix="/api/v1")
install_error_handlers(app)         # n'intercepte que les erreurs de ce paquet
# à l'arrêt : await service.aclose() ; pour /ready : service.readiness()
```

`dev_server.py` est un **harnais de développement** ; l'application de production est celle du MLOps.

| Méthode | Chemin | Workflow |
|---|---|---|
| POST | `/api/v1/tutor/experiences` | A — expérience adaptative (intention → format) |
| POST | `/api/v1/tutor/answers` | B — correction + remédiation |
| POST | `/api/v1/tutor/recommendations` | D — prochaine activité |
| POST | `/api/v1/tutor/recommendations/{id}/outcome` | D — retour envoyé au RL |
| GET  | `/api/v1/tutor/progress` | progression de l'élève (sans modèle) |
| POST | `/api/v1/teacher/reports` | C — rapport agrégé, enseignant de la classe |
| GET  | `/api/v1/assets/{id}` | figures du cours (identifiants opaques, jeton requis) |

Erreurs : `{"error": {"code", "message", "request_id"}}`. Une panne de dépendance ne donne pas de 5xx :
réponse `200` avec `status: "degraded" | "failed"` et un bloc de secours ; seul le délai global dépasse en `504`.

## Garanties vérifiées par les tests

- Les corrigés ne quittent jamais le serveur ; une question corrigée n'est plus rejouable (le retour révèle la réponse).
- L'identité vient du jeton, jamais du corps de requête ; le rôle n'est jamais lu d'un en-tête.
- L'historique et la performance de l'élève sont **calculés côté serveur** (le client ne peut pas les fournir).
- Les passages du cours sont transmis comme **données non fiables** ; les sorties du LLM n'engendrent jamais de HTML.
- Une réponse n'est présentée « vérifiée » que pour les contrôles réellement exécutés (`checks_run`).
- Aucune donnée simulée ne passe pour réelle : `meta.simulated` + `simulated_services`.
- Aucune adaptation d'accessibilité n'est déduite du comportement : uniquement les préférences déclarées.
- Les logs/télémétrie ne contiennent aucun texte d'élève (identifiants, comptes et durées uniquement).

## Authentification (développement uniquement)

`DevTokenAuthenticator` associe des jetons à des identités pseudonymes de test. **Ce n'est pas une
authentification réelle** : elle refuse de démarrer hors `development/test`, et sans jetons configurés
toute requête est rejetée. À remplacer en implémentant le protocole `Authenticator` (`auth.py`).

## Télémétrie

`tutor.adapter.call`, `tutor.verification.result`, `tutor.workflow.completed` : workflow, résultat,
latence, tentatives, codes d'erreur, versions de prompt/modèle, `request_id`. Sink par défaut : lignes
JSON. Le MLOps branche MLflow Tracing / Prometheus avec `Telemetry(sink)`, sans autre changement.

## Limites connues

- Les services **RL** et **données d'apprentissage** n'existent pas encore : leurs adaptateurs HTTP sont
  testés contre des réponses simulées (respx), jamais contre le vrai service.
- Les appels `Tutor.ask/quiz` ne filtrent pas par document : avec plusieurs cours indexés, la génération
  peut citer un autre cours (la vérification des pages le détecte pour les quiz). Demande faite à l'équipe GenAI : `doc_id` en paramètre.
- Stores (questions émises, historique) **en mémoire** : perdus au redémarrage, non partagés entre instances.
- La description d'image dépend d'un modèle de vision configuré ; non évaluée sur de vrais cours.
- L'adaptation des couleurs est une heuristique (simulation Machado + décalage d'erreur), pas un dispositif médical.
- Le catalogue d'activités proposé au RL est une grille par défaut (type × difficulté).

Contrats détaillés et demandes aux coéquipiers : [`docs/agentic/INTEGRATION.md`](../../docs/agentic/INTEGRATION.md).
