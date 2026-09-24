$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location (Join-Path $repoRoot 'frontend')
try {
    npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed' }
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed' }
} finally {
    Pop-Location
}

Push-Location $repoRoot
try {
    uv run ruff check backend scripts/measure_baseline.py scripts/measure_performance_acceptance.py scripts/manage_local_backup.py scripts/measure_backup_restore_acceptance.py scripts/archive_production_licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed' }
    uv run python scripts/archive_production_licenses.py verify --archive-dir docs/licenses/production
    if ($LASTEXITCODE -ne 0) { throw 'Production dependency license verification failed' }
    uv run pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
} finally {
    Pop-Location
}
