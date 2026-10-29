# Monitoring des données et traces distribuées

Cette étape utilise uniquement des données synthétiques. Aucun identifiant, contenu de
cours privé ou historique réel d'élève ne doit être ajouté aux rapports ou attributs de
trace.

## Evidently AI

Le script `scripts/generate_drift_report.py` construit deux périodes déterministes de
240 lignes :

- la période de référence représente le comportement synthétique initial ;
- la période courante introduit volontairement des sessions plus longues, des scores de
  quiz plus faibles, davantage d'interactions et une distribution de difficulté modifiée.

Evidently 0.7.23 analyse cinq colonnes avec `DataDriftPreset` :

- `session_duration_minutes`, `quiz_score` et `interaction_count` sont numériques ;
- `difficulty` et `accessibility_mode` sont catégorielles ;
- `sample_id` sert uniquement d'identifiant et n'entre pas dans le calcul.

Avec 240 observations par période, Evidently sélectionne ici le test de Kolmogorov-Smirnov
pour les variables numériques et le test du khi-deux pour les variables catégorielles.
Une colonne est signalée en drift lorsque sa p-value est inférieure à `0.05`. Le dataset
est signalé lorsque la part de colonnes en drift atteint `0.40`.

Le résultat réellement généré détecte quatre colonnes sur cinq, soit `0.80`. La variable
`accessibility_mode` reste volontairement stable et sert de contrôle.

Sous Windows, une politique Application Control peut bloquer certaines DLL NumPy. Le
conteneur Linux dédié évite de désactiver cette protection :

```powershell
docker compose --profile reports build evidently-report
docker compose --profile reports run --rm evidently-report
```

Sorties :

- `monitoring/evidently/data/reference_period.csv` ;
- `monitoring/evidently/data/current_period.csv` ;
- `monitoring/evidently/reports/data_drift_report.html` ;
- `monitoring/evidently/reports/data_drift_snapshot.json` ;
- `monitoring/evidently/reports/drift_summary.json`.

Ouvrir le rapport local :

```powershell
Start-Process .\monitoring\evidently\reports\data_drift_report.html
```

## OpenTelemetry

`app/telemetry.py` instrumente automatiquement les requêtes FastAPI. Les routes de santé
et de métriques sont exclues pour limiter le bruit. Les traces sont désactivées par défaut
hors conteneur, ce qui garde les tests unitaires isolés.

Dans Docker Compose, elles sont activées avec un export console par défaut :

```powershell
docker compose up --build -d api
Invoke-RestMethod http://localhost:8000/generate-quiz -Method Post `
  -ContentType application/json `
  -Body '{"subject":"Mathématiques","topic":"Fractions","number_of_questions":2}'
docker compose logs api
```

Le service optionnel `otel-collector` accepte OTLP/HTTP sur le port 4318, OTLP/gRPC sur
4317 et écrit les spans reçus avec son exporteur `debug` :

```powershell
$env:OTEL_TRACES_EXPORTER = "otlp"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://otel-collector:4318"
docker compose --profile observability up -d otel-collector
docker compose up -d --force-recreate api

# Effectuer une requête, puis consulter les spans
docker compose logs otel-collector
```

Pour revenir à l'export console :

```powershell
Remove-Item Env:OTEL_TRACES_EXPORTER -ErrorAction SilentlyContinue
Remove-Item Env:OTEL_EXPORTER_OTLP_ENDPOINT -ErrorAction SilentlyContinue
docker compose up -d --force-recreate api
docker compose --profile observability stop otel-collector
```

L'exporteur `debug` sert à la démonstration locale. Pour un environnement partagé, le
Collector pourra router OTLP vers Jaeger, Tempo ou une autre plateforme sans modifier
l'instrumentation FastAPI.

## Future intégration RAG et RL

Les futurs modules peuvent créer des spans enfants autour des opérations suivantes :

- RAG : extraction, recherche vectorielle, génération, validation et version d'index ;
- RL : chargement de politique, décision, score synthétique et version de politique ;
- LLM : fournisseur, modèle, version de prompt, latence et volumes de tokens.

Ne pas mettre dans les attributs de spans les réponses, prompts complets, documents,
besoins d'accessibilité individuels ou identifiants d'élèves. Utiliser des identifiants
techniques non personnels, des versions et des métriques agrégées.
