param(
    [int]$TimeoutSeconds = 600,
    [switch]$SkipBuild,
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Program,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    Write-Host "`n> $Program $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "La commande a echoue avec le code $LASTEXITCODE : $Program $($Arguments -join ' ')"
    }
}

function Wait-AirflowDag {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DagId,
        [Parameter(Mandatory = $true)]
        [string]$RunId
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $output = & docker compose exec -T airflow-api-server airflow dags state $DagId $RunId 2>&1
        $stateMatch = $output | Select-String -Pattern "^(queued|running|success|failed|upstream_failed)$" | Select-Object -Last 1
        $state = if ($stateMatch) { $stateMatch.Line } else { "en attente" }

        if ($state -eq "success") {
            Write-Host "$DagId termine avec succes." -ForegroundColor Green
            return
        }
        if ($state -in @("failed", "upstream_failed")) {
            throw "$DagId a termine dans l'etat $state. Consultez : docker compose logs airflow-scheduler"
        }

        Write-Host "$DagId : $state"
        Start-Sleep -Seconds 5
    }

    throw "Delai depasse pour $DagId apres $TimeoutSeconds secondes."
}

function Start-AndWaitDag {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DagId
    )

    $runId = "manual__full_flow_$($DagId)_$(Get-Date -Format 'yyyyMMddTHHmmssfff')"
    Invoke-Native docker compose exec -T airflow-api-server airflow dags unpause $DagId
    Invoke-Native docker compose exec -T airflow-api-server airflow dags trigger -r $runId $DagId
    Wait-AirflowDag -DagId $DagId -RunId $runId
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Environnement virtuel introuvable : $venvPython"
}

Push-Location $projectRoot
try {
    Write-Host "=== 1/6 - Qualite, tests et dependances ===" -ForegroundColor Yellow
    Invoke-Native $venvPython scripts/run_ci_checks.py --skip-docker

    Write-Host "=== 2/6 - Validation et demarrage Docker Compose ===" -ForegroundColor Yellow
    Invoke-Native docker compose config --quiet
    $upArguments = @("compose", "up", "-d", "--wait", "--wait-timeout", "300")
    if (-not $SkipBuild) {
        $upArguments += "--build"
    }
    Invoke-Native docker @upArguments

    Write-Host "=== 3/6 - Verification des services ===" -ForegroundColor Yellow
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 10
    if ($health.status -ne "ok") {
        throw "FastAPI n'est pas saine."
    }
    Invoke-RestMethod -Uri "http://localhost:5000/health" -TimeoutSec 10 | Out-Null
    Invoke-RestMethod -Uri "http://localhost:9090/-/healthy" -TimeoutSec 10 | Out-Null
    Invoke-RestMethod -Uri "http://localhost:3000/api/health" -TimeoutSec 10 | Out-Null
    Invoke-RestMethod -Uri "http://localhost:8080/api/v2/monitor/health" -TimeoutSec 10 | Out-Null

    Write-Host "=== 4/6 - Test du flow FastAPI ===" -ForegroundColor Yellow
    $quizBody = @{
        subject = "Mathematiques"
        topic = "Fractions"
        difficulty = "moyen"
        number_of_questions = 2
        accessibility_needs = @("lecture simplifiee")
    } | ConvertTo-Json
    $quiz = Invoke-RestMethod -Uri "http://localhost:8000/generate-quiz" -Method Post -ContentType "application/json" -Body $quizBody
    if (-not $quiz.is_simulated -or $quiz.questions.Count -ne 2) {
        throw "La generation de quiz n'a pas retourne le resultat attendu."
    }

    $activityBody = @{
        performance_score = 0.35
        attempts = 3
        current_topic = "Fractions"
        accessibility_needs = @()
    } | ConvertTo-Json
    $activity = Invoke-RestMethod -Uri "http://localhost:8000/next-activity" -Method Post -ContentType "application/json" -Body $activityBody
    if ($activity.activity_type -ne "remediation") {
        throw "La politique RL simulee n'a pas retourne remediation."
    }

    Write-Host "=== 5/6 - Pipelines Airflow RAG, RL et evaluation ===" -ForegroundColor Yellow
    Start-AndWaitDag -DagId "rag_pipeline_demo"
    Start-AndWaitDag -DagId "rl_pipeline_demo"
    Start-AndWaitDag -DagId "mlops_evaluation_demo"

    Write-Host "=== 6/6 - Verification du manifeste final ===" -ForegroundColor Yellow
    $manifest = Invoke-RestMethod -Uri "http://localhost:8000/artifacts/validated" -TimeoutSec 10
    if ($manifest.status -ne "available") {
        throw "Le manifeste final n'est pas disponible dans FastAPI."
    }
    if ($manifest.overall_status -ne "validated") {
        throw "Le manifeste existe mais son statut est : $($manifest.overall_status)"
    }

    Write-Host "`nFLOW COMPLET VALIDE" -ForegroundColor Green
    Write-Host "FastAPI, MLflow, Airflow, Prometheus et Grafana sont accessibles."
    Write-Host "Les DAGs RAG, RL et evaluation ont reussi; le manifeste est valide."
}
finally {
    if ($StopAfter) {
        Write-Host "`nArret des services Docker Compose..." -ForegroundColor Yellow
        & docker compose down
    }
    Pop-Location
}
