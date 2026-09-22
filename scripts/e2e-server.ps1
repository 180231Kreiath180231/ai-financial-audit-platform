$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot '.runtime'))
$dataDir = [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot 'e2e-data'))

if ($dataDir -ne (Join-Path $runtimeRoot 'e2e-data')) {
    throw "拒绝清理非预期的 E2E 目录：$dataDir"
}
if (Test-Path -LiteralPath $dataDir) {
    Remove-Item -LiteralPath $dataDir -Recurse -Force
}

try {
    & (Join-Path $PSScriptRoot 'dev.ps1') -NoOpen -BackendPort 8100 -FrontendPort 5174 -DataDir $dataDir
} finally {
    if ($dataDir -eq (Join-Path $runtimeRoot 'e2e-data') -and (Test-Path -LiteralPath $dataDir)) {
        Remove-Item -LiteralPath $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
