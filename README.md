# Tuteur éducatif inclusif — socle MLOps local

Ce dépôt contient le socle local et reproductible du projet académique **Tuteur
éducatif inclusif**. À cette étape, l'API utilise exclusivement des réponses
simulées et des données synthétiques : aucun modèle RAG/RL ni aucune donnée réelle
d'élève ne sont utilisés.

## Prérequis

- Windows avec Python 3.13 et Git
- PowerShell

## Installation locale

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si la politique PowerShell bloque l'activation, les commandes peuvent être lancées
directement avec `.\.venv\Scripts\python.exe`.

## Lancer l'API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

L'API est alors disponible sur <http://127.0.0.1:8000>, sa documentation Swagger
sur <http://127.0.0.1:8000/docs> et son schéma OpenAPI sur
<http://127.0.0.1:8000/openapi.json>.

## Vérifications

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## Endpoints de démonstration

- `GET /health` : état de l'API.
- `POST /generate-quiz` : fabrique un quiz synthétique déterministe.
- `POST /student-answer` : compare une réponse à une réponse attendue fournie pour la simulation.
- `POST /next-activity` : applique des règles simples simulant une future décision RL.

Toutes les sorties IA sont explicitement identifiées comme simulées.

## Docker Compose

Docker Desktop doit utiliser le contexte `desktop-linux` avec WSL2. La
configuration Compose monte `./app` en lecture seule dans le conteneur pour
faciliter le développement local, tout en conservant le code dans l'image.

Pour personnaliser la configuration, copier `.env.example` vers `.env`, puis
modifier les valeurs locales. Le fichier `.env` est ignoré par Git.

```powershell
# Construire et démarrer l'API en arrière-plan
docker compose up --build -d

# Vérifier les services et leurs healthchecks
docker compose ps

# Consulter les logs
docker compose logs -f api

# Tester l'API
Invoke-RestMethod http://localhost:8000/health

# Arrêter et supprimer les conteneurs/réseaux Compose
docker compose down
```

Le port hôte peut être changé sans modifier `compose.yaml` :

```powershell
$env:API_PORT = "8080"
docker compose up --build -d
```

Dans ce cas, Swagger est accessible sur <http://localhost:8080/docs>.

## MLflow Tracking et Tracing

Le service MLflow utilise une base SQLite persistante pour les métadonnées et un
volume Docker distinct pour les artefacts. Son interface est disponible sur
<http://localhost:5000> après le démarrage de Compose.

```powershell
# Démarrer l'API et MLflow
docker compose up --build -d

# Créer trois runs et une trace entièrement synthétiques
.\.venv\Scripts\python.exe scripts\run_mlflow_demo.py

# Vérifier les runs, métriques, artefacts et traces enregistrés
.\.venv\Scripts\python.exe scripts\verify_mlflow.py

# Afficher l'état et les logs
docker compose ps
docker compose logs mlflow
```

L'expérience s'appelle `tuteur-inclusif-demo`. Les métriques
`synthetic_quality_score` ne sont pas des évaluations de modèles réels et ne
doivent pas être interprétées comme telles. Les volumes `mlflow_data` et
`mlflow_artifacts` survivent à un `docker compose down`. La commande
`docker compose down -v` les supprimerait définitivement et ne doit être utilisée
que pour réinitialiser volontairement les données locales.

## DVC et données pédagogiques

Le catalogue synthétique `data/raw/course_catalog.csv` est suivi par DVC. Le
remote `local-storage` est un dossier de test local, sans serveur permanent.

```powershell
.\.venv\Scripts\dvc.exe status
.\.venv\Scripts\dvc.exe remote list
.\.venv\Scripts\dvc.exe pull
```

Le guide détaillé de versionnement, de restauration et de migration vers un
stockage partagé se trouve dans `docs/DVC_VERSIONING.md`.

## Monitoring Prometheus et Grafana

FastAPI expose ses métriques sur <http://localhost:8000/metrics>. Prometheus est
accessible sur <http://localhost:9090> et Grafana sur <http://localhost:3000>.
Les identifiants Grafana locaux par défaut sont `admin` / `admin` et peuvent être
changés dans `.env`.

```powershell
# Démarrer ou mettre à jour la stack
docker compose up --build -d

# Générer 50 requêtes synthétiques, dont des validations HTTP 422
.\.venv\Scripts\python.exe scripts\generate_traffic.py

# Vérifier les services
docker compose ps
```

La datasource Prometheus et le dashboard `Tuteur inclusif — FastAPI` sont
provisionnés automatiquement. Le dashboard affiche la disponibilité, le nombre
de requêtes, le débit par endpoint, la latence moyenne et p95 et le taux d'erreur.

## Orchestration Apache Airflow

Airflow 3.3.2 orchestre uniquement les traitements batch. FastAPI continue de répondre
directement aux interactions utilisateur et peut consulter le dernier manifeste produit
via `GET /artifacts/validated`.

```powershell
# Construire l'image Airflow enrichie puis initialiser PostgreSQL
docker compose build airflow-init
docker compose up airflow-init

# Démarrer tous les services
docker compose up -d
docker compose ps

# Autoriser les déclenchements manuels (une seule fois)
docker compose exec -T airflow-api-server airflow dags unpause rag_pipeline_demo
docker compose exec -T airflow-api-server airflow dags unpause rl_pipeline_demo
docker compose exec -T airflow-api-server airflow dags unpause mlops_evaluation_demo

# Déclencher manuellement les trois démonstrations
docker compose exec -T airflow-api-server airflow dags trigger rag_pipeline_demo
docker compose exec -T airflow-api-server airflow dags trigger rl_pipeline_demo
docker compose exec -T airflow-api-server airflow dags trigger mlops_evaluation_demo
```

L'interface Airflow est disponible sur <http://localhost:8080> avec les identifiants
locaux `airflow` / `airflow`. Les trois DAGs sont manuels et utilisent exclusivement des
mocks et des données synthétiques. Le guide détaillé, les commandes de diagnostic et le
contrat d'artefacts se trouvent dans `docs/AIRFLOW_ORCHESTRATION.md`.

## Evidently et OpenTelemetry

Le monitoring de données compare deux périodes entièrement synthétiques et génère un
rapport Evidently local :

```powershell
docker compose --profile reports build evidently-report
docker compose --profile reports run --rm evidently-report
Start-Process .\monitoring\evidently\reports\data_drift_report.html
```

FastAPI produit des traces OpenTelemetry dans ses logs par défaut. Un Collector optionnel
peut recevoir les traces via OTLP avec le profil `observability`. Les métriques de drift,
les variables d'environnement, les commandes de vérification et les règles empêchant
l'exposition de données sensibles sont documentées dans `docs/OBSERVABILITY.md`.

## Intégration continue

Le workflow `.github/workflows/ci.yml` s'exécute sur les pull requests ciblant `main`
et peut aussi être lancé manuellement. Il installe les dépendances, exécute Ruff, Pytest
et `pip check`, puis construit et teste l'image Docker FastAPI.

Les mêmes contrôles peuvent être reproduits localement sous PowerShell :

```powershell
.\scripts\run_ci_checks.ps1
```

Si la stratégie Windows interdit les scripts, utiliser directement le lanceur Python
(sans modifier la stratégie système) :

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_checks.py
```

Pour n'exécuter que les contrôles Python :

```powershell
.\scripts\run_ci_checks.ps1 -SkipDocker
```

La procédure de transfert vers le dépôt commun, les précautions contre les conflits et
la checklist de pull request sont détaillées dans `INTEGRATION.md`.

