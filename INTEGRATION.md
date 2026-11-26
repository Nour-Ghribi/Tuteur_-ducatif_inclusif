# Intégration de l'infrastructure MLOps/LLMOps

Ce document décrit comment transférer ce prototype vers le dépôt commun sans modifier
l'historique Git actuel et sans écraser le travail de l'équipe.

## 1. Préparer une copie propre du dépôt commun

Ces commandes sont à exécuter uniquement après avoir reçu l'URL et les droits d'accès :

```bash
git clone <URL_DU_DEPOT_COMMUN> tuteur-educatif-inclusif
cd tuteur-educatif-inclusif
git switch main
git pull --ff-only
git switch -c feature/mlops
```

Ne pas ajouter de remote à ce prototype. La branche `feature/mlops` doit être créée dans
la copie du dépôt commun, pas dans ce dossier de travail.

## 2. Transférer les fichiers par groupes cohérents

Comparer d'abord les deux arborescences, puis transférer manuellement les éléments utiles :

1. API et tests : `app/`, `tests/`, `pyproject.toml` et les dépendances de
   `requirements.txt`.
2. Conteneurs : `Dockerfile`, `.dockerignore`, `compose.yaml` et `.env.example`.
3. Expérimentation et données de démonstration : `mlruns/`, `data/`, `models/`,
   `params.yaml`, `dvc.yaml` et les fichiers `.dvc` versionnables.
4. Orchestration : `orchestration/`.
5. Observabilité : `monitoring/`, `grafana/`, `otel-collector-config.yaml` et les
   dépendances d'observabilité.
6. CI et documentation : `.github/workflows/ci.yml`, `scripts/run_ci_checks.py`,
   `scripts/run_ci_checks.ps1`, `README.md` et ce fichier.

Ne jamais transférer `.git/`, `.venv/`, `.env`, `.dvc/cache/`, `.dvc-storage/`, des
secrets, des données réelles d'élèves, des journaux d'exécution ou des volumes locaux.

## 3. Éviter et résoudre les conflits

- Ne pas remplacer aveuglément `README.md`, `requirements.txt`, `pyproject.toml`,
  `Dockerfile` ou `compose.yaml` s'ils existent déjà.
- Fusionner les dépendances Python et conserver les contraintes de versions du dépôt commun.
- Fusionner les services Compose, réseaux, volumes, ports et variables d'environnement en
  conservant les services déjà utilisés par l'équipe.
- Adapter les imports de `app/` si le dépôt commun possède déjà son propre package backend.
- Choisir avec l'équipe le stockage DVC partagé. Le cache et le remote locaux du prototype
  ne doivent pas être intégrés comme solution d'équipe.
- Après chaque groupe transféré, examiner `git diff` et exécuter `git diff --check`.

## 4. Installer et reproduire les contrôles CI

Sous PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\run_ci_checks.ps1
```

Si Windows bloque les fichiers `.ps1`, utiliser le lanceur multiplateforme sans changer
la stratégie d'exécution de la machine :

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_checks.py
```

Pour ignorer temporairement Docker :

```powershell
.\scripts\run_ci_checks.ps1 -SkipDocker
```

Commande multiplateforme équivalente, depuis un environnement Python activé :

```bash
python scripts/run_ci_checks.py
```

Le lanceur exécute Ruff, Pytest, `pip check`, la construction de l'image FastAPI et un
test d'import dans le conteneur. Le workflow GitHub Actions reprend les mêmes contrôles
sur chaque pull request ciblant `main`.

## 5. Vérifier l'ensemble avant la pull request

En plus du lanceur CI, vérifier selon les composants transférés :

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Contrôler l'API, MLflow, Airflow, Prometheus, Grafana et le collecteur OpenTelemetry avec
les procédures du `README.md`. N'utiliser que les données synthétiques fournies.

## 6. Préparer la pull request

Une fois les droits GitHub disponibles et les vérifications réussies :

```bash
git status --short
git diff --check
git add <fichiers_validés_explicitement>
git commit -m "feat: add local MLOps and LLMOps infrastructure"
git push -u origin feature/mlops
```

Ouvrir ensuite une pull request de `feature/mlops` vers `main`. Sa description doit
indiquer les services ajoutés, les ports, les commandes de validation, les résultats des
tests, les variables à configurer et les limites connues. Vérifier la première exécution
réelle de GitHub Actions dans la pull request : la validation locale du YAML ne remplace
pas l'exécution sur un runner GitHub hébergé.

Checklist finale :

- [ ] aucun secret ni donnée réelle d'élève dans le diff ;
- [ ] conflits avec les fichiers communs résolus manuellement ;
- [ ] Ruff, Pytest et `pip check` réussis ;
- [ ] image FastAPI construite et testée ;
- [ ] configuration Compose valide et services nécessaires sains ;
- [ ] workflow GitHub Actions réellement réussi sur la pull request ;
- [ ] documentation et variables d'environnement à jour.
