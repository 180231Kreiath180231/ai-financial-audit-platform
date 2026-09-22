$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location (Join-Path $repoRoot 'frontend')
try {
    npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw '前端 lint 失败' }
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw '前端单元测试失败' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally {
    Pop-Location
}

Push-Location $repoRoot
try {
    uv run ruff check backend scripts/measure_baseline.py
    if ($LASTEXITCODE -ne 0) { throw '后端 lint 失败' }
    uv run pytest
    if ($LASTEXITCODE -ne 0) { throw '后端测试失败' }
} finally {
    Pop-Location
}
