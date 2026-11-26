param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Python virtuel introuvable: $venvPython. Creez .venv et installez requirements.txt."
}

$scriptArguments = @((Join-Path $PSScriptRoot "run_ci_checks.py"))
if ($SkipDocker) {
    $scriptArguments += "--skip-docker"
}

& $venvPython @scriptArguments
exit $LASTEXITCODE
