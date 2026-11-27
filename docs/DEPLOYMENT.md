# Deployment Guide

This document covers all deployment options for the inclusive educational tutor,
from a single VPS to a multi-service Kubernetes cluster.

---

## 1. Prerequisites (all environments)

| Requirement | Minimum | Recommended |
|---|---|---|
| CPU | 2 cores | 4+ cores (video generation is CPU-bound) |
| RAM | 4 GB | 8 GB (LLM in-process needs ~3–4 GB) |
| Disk | 10 GB | 50 GB (ChromaDB + MLflow artifacts + video) |
| Python | 3.11 | 3.11 |
| Docker | 24+ | 25+ |
| Node.js | 18+ | 20+ (frontend build only) |

---

## 2. Local development

```bash
# Full stack via Docker Compose
cp .env.example .env
# Edit .env with your LLM API keys
docker compose up

# Frontend dev server (hot reload)
cd frontend && npm install && npm run dev
```

Accessible at http://localhost:5173 (frontend) and http://localhost:8000 (API).

---

## 3. Single server / VPS deployment

### Setup

```bash
# On the server
git clone https://github.com/Nour-Ghribi/Tuteur_-ducatif_inclusif.git /opt/tuteur
cd /opt/tuteur
git checkout integration/main

cp .env.example .env
# Set production values in .env:
#   TUTOR_ENVIRONMENT=production
#   TUTOR_ALLOW_MOCKS=false
#   TUTOR_GENAI_BACKEND=http   (or tuteur if LLM runs on same server)
#   LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
#   TUTOR_PROFILE_DB_PATH=/data/profiles.db
#   TUTOR_LEDGER_DB_PATH=/data/ledger.db
#   GRAFANA_ADMIN_PASSWORD=<strong-password>
#   AIRFLOW_DB_PASSWORD=<strong-password>

docker compose up -d
```

### nginx reverse proxy (recommended)

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Frontend (built static files)
    location / {
        root /opt/tuteur/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # MLflow (restrict access in production)
    location /mlflow/ {
        proxy_pass http://localhost:5000/;
        auth_basic "MLflow";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }

    # Grafana
    location /grafana/ {
        proxy_pass http://localhost:3000/;
    }
}
```

---

## 4. GitHub Actions CI/CD

### Workflows

| Workflow | Trigger | Jobs |
|---|---|---|
| `ci.yml` | PR + push to `integration/main` | Ruff, Pytest (3 suites), Frontend build, Docker smoke test |
| `deploy.yml` | Push to `main` or manual | Build+push images to ghcr.io → deploy staging → (manual) production |

### Required secrets

Set these in **Settings → Secrets → Actions**:

| Secret | Used by | Description |
|---|---|---|
| `STAGING_HOST` | deploy.yml | IP or hostname of staging server |
| `STAGING_USER` | deploy.yml | SSH username |
| `STAGING_SSH_KEY` | deploy.yml | Private SSH key for staging |
| `PROD_HOST` | deploy.yml | Production server hostname |
| `PROD_USER` | deploy.yml | SSH username |
| `PROD_SSH_KEY` | deploy.yml | Private SSH key for production |
| `PROD_DOMAIN` | deploy.yml | Production domain for health check |

The `GITHUB_TOKEN` is provided automatically for image push to `ghcr.io`.

### Deployment flow

```
developer pushes to integration/main
  → CI runs (ruff + pytest + docker build)
  → PR opened to main
  → CI runs again on the PR
  → PR merged to main
  → deploy.yml triggers automatically
  → images pushed to ghcr.io
  → staging deployed and health-checked
  → (manual) production deployment via workflow_dispatch
```

---

## 5. Railway / Render (PaaS)

Both platforms support Docker Compose or Dockerfile deployments.

### Railway

1. Connect your GitHub repository
2. Select `compose.yaml` as the deployment source
3. Set environment variables in the Railway dashboard (copy from `.env.example`)
4. Deploy — Railway handles scaling and HTTPS automatically

### Render

1. Create a new **Web Service**, connect the repo
2. Set **Build Command**: `docker build -t api .`
3. Set **Start Command**: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables from `.env.example`
5. Create a separate service for the RL microservice (`backend/rl/Dockerfile`)

---

## 6. Kubernetes (AWS EKS / GCP GKE / Azure AKS)

### Helm chart structure (create in `deploy/helm/tuteur/`)

```
deploy/helm/tuteur/
├── Chart.yaml
├── values.yaml          # default values (image tags, replica counts, env)
├── values-staging.yaml  # staging overrides
├── values-prod.yaml     # production overrides
└── templates/
    ├── api-deployment.yaml
    ├── api-service.yaml
    ├── rl-deployment.yaml
    ├── rl-service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    └── secret.yaml      # references K8s Secrets for API keys
```

### Minimal deployment command

```bash
helm upgrade --install tuteur ./deploy/helm/tuteur \
  --namespace tuteur \
  --create-namespace \
  -f deploy/helm/tuteur/values-staging.yaml \
  --set image.api.tag=sha-abc1234 \
  --set image.rl.tag=sha-abc1234
```

### Recommended architecture

```
LoadBalancer (AWS ALB / GCP GLB)
  ├── Ingress (nginx-ingress)
  │   ├── /        → frontend (nginx static, 2 replicas)
  │   ├── /api/    → api (FastAPI, 2–4 replicas, HPA)
  │   ├── /mlflow/ → mlflow (1 replica, PVC for artifacts)
  │   └── /grafana/→ grafana (1 replica)
  │
  ├── api (ClusterIP) → rl (ClusterIP, 1 replica)
  ├── api → mlflow (ClusterIP)
  │
  ├── PersistentVolumeClaims:
  │   ├── mlflow-data (5Gi)
  │   ├── chroma-data (10Gi)
  │   └── images-data (20Gi)
  │
  └── ConfigMaps + Secrets (from K8s Secrets Manager / AWS Secrets Manager)
```

---

## 7. Data persistence

| Data | Volume | Notes |
|---|---|---|
| ChromaDB index | `tutor_chroma` | Rebuild with `tuteur ingest` if lost |
| Extracted images | `tutor_images` | Rebuild from PDFs if lost |
| Student profiles | `TUTOR_PROFILE_DB_PATH` SQLite | Back up daily |
| Student ledger (RL+badges) | `TUTOR_LEDGER_DB_PATH` SQLite | Back up daily |
| MLflow experiments | `mlflow_data` | Back up weekly |
| Airflow metadata | `airflow_postgres_data` | Back up weekly |

### Backup script (cron)

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR=/backups/tuteur/$DATE

mkdir -p $BACKUP_DIR

# SQLite databases
cp /data/profiles.db $BACKUP_DIR/profiles.db
cp /data/ledger.db   $BACKUP_DIR/ledger.db

# MLflow artifacts (compress)
tar -czf $BACKUP_DIR/mlflow-artifacts.tar.gz /data/mlflow/

echo "Backup completed: $BACKUP_DIR"
```

---

## 8. Monitoring

| Dashboard | URL | Credentials |
|---|---|---|
| Grafana | `:3000` | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | `:9090` | — |
| Airflow | `:8080` | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` |
| MLflow | `:5000` | — (add auth in production) |

Grafana dashboards are pre-provisioned at startup:
- `fastapi-overview.json` — request rate, latency, error rate
- `airflow-overview.json` — DAG run status and duration

Prometheus scrapes `/metrics` on the API service (Prometheus client + OpenTelemetry).

---

## 9. Scaling considerations

| Component | Stateless? | Scale strategy |
|---|---|---|
| `api` | ✅ (in-memory stores → Redis in prod) | Horizontal, HPA on CPU |
| `rl` | ✅ | Horizontal |
| `frontend` | ✅ | CDN or static hosting |
| `mlflow` | ⚠️ SQLite backend | Single replica; switch to Postgres for HA |
| `airflow` | ⚠️ Postgres-backed | Scheduler: 1 replica; workers: horizontal |
| ChromaDB | ⚠️ File-backed | Single replica; switch to Qdrant for HA |

For production with >100 concurrent users, replace:
- `InMemoryProfileStore` → `SQLiteProfileStore` (already implemented, set `TUTOR_PROFILE_DB_PATH`)
- `InMemoryStudentHistory` → Redis-backed store
- ChromaDB local → Qdrant or Weaviate (change `VectorStore` backend in `config.py`)
