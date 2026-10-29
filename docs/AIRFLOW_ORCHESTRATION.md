# Orchestration Airflow locale

Cette configuration utilise Apache Airflow 3.3.2 avec `LocalExecutor` et PostgreSQL.
Elle est conçue pour une démonstration locale : elle n'utilise ni Kubernetes, ni
Kubeflow, ni données réelles d'élèves.

## Services

- `airflow-postgres` conserve les métadonnées Airflow.
- `airflow-api-server` sert l'interface et l'API sur le port 8080.
- `airflow-scheduler` planifie et exécute localement les tâches.
- `airflow-dag-processor` analyse séparément les fichiers de DAG.
- `airflow-statsd` convertit les métriques Airflow pour Prometheus.
- `airflow-init` applique les migrations et crée le compte local au premier démarrage.

Redis et Celery ne sont volontairement pas utilisés : `LocalExecutor` est suffisant
pour les petits traitements batch de cette démonstration et consomme moins de ressources.

## Démarrage

```powershell
docker compose build airflow-init
docker compose up airflow-init
docker compose up -d
docker compose ps
```

L'interface est disponible sur <http://localhost:8080>. Les identifiants locaux par
défaut sont `airflow` / `airflow`. Ils doivent être changés dans un fichier `.env`
pour toute utilisation au-delà de la démonstration locale.

## DAGs

- `rag_pipeline_demo` prépare un cours synthétique, des chunks, des embeddings et un
  index fictifs, puis génère et évalue un quiz simulé.
- `rl_pipeline_demo` transforme des interactions synthétiques, simule une politique
  adaptative et publie une version de cette politique.
- `mlops_evaluation_demo` lit les dernières versions RAG et RL disponibles, les compare
  à des seuils configurables et publie un manifeste validé ou refusé.

Les trois DAGs ont `schedule=None` et se déclenchent manuellement. Les pipelines RAG et
RL sont indépendants. Le pipeline d'évaluation peut être lancé à tout moment : si un
artefact manque, il produit une décision `refused` explicite au lieu de supposer un ordre
d'exécution caché.

```powershell
# À faire une seule fois après la création des DAGs
docker compose exec -T airflow-api-server airflow dags unpause rag_pipeline_demo
docker compose exec -T airflow-api-server airflow dags unpause rl_pipeline_demo
docker compose exec -T airflow-api-server airflow dags unpause mlops_evaluation_demo

docker compose exec -T airflow-api-server airflow dags trigger rag_pipeline_demo
docker compose exec -T airflow-api-server airflow dags trigger rl_pipeline_demo
docker compose exec -T airflow-api-server airflow dags trigger mlops_evaluation_demo
```

Les DAGs sont créés en pause afin qu'un premier démarrage ne lance jamais de traitement
implicitement. Airflow garde un déclenchement en file d'attente tant que le DAG concerné
n'a pas été dépausé.

## Artefacts, XCom et intégration FastAPI

Les fichiers sont écrits sous `orchestration/shared/` et non dans XCom. XCom transporte
uniquement des chemins et de petites métadonnées. Les sorties générées sont ignorées par
Git ; seuls les jeux d'entrée synthétiques sont suivis.

Le manifeste stable est `orchestration/shared/registry/validation/latest.json`.
FastAPI le monte en lecture seule et l'expose via `GET /artifacts/validated`. Une requête
utilisateur ne déclenche jamais un DAG : Airflow reste réservé aux traitements batch.

## Observabilité et erreurs

Chaque tâche possède deux retries, un délai de 20 secondes et un timeout de cinq minutes.
Les logs persistent dans le volume `airflow_logs`. Les expériences et artefacts sont
envoyés à l'expérience MLflow `tuteur-inclusif-airflow-demo`.

Le StatsD exporter expose les compteurs de succès/échec, les durées et les heartbeats sur
le réseau Compose. Prometheus les collecte avec le job `airflow`; Grafana provisionne le
dashboard `Tuteur inclusif — Airflow`.

```powershell
docker compose logs airflow-scheduler
docker compose logs airflow-dag-processor
Invoke-RestMethod http://localhost:9090/api/v1/targets
```

## Arrêt

```powershell
docker compose down
```

Les volumes PostgreSQL et de logs persistent. `docker compose down -v` les efface et ne
doit être utilisé que pour une réinitialisation volontaire.
