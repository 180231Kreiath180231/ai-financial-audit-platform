param(
    [switch]$NoOpen,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$DataDir = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $repoRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $resolvedDataDir = Join-Path $repoRoot 'data\runtime'
} elseif ([System.IO.Path]::IsPathRooted($DataDir)) {
    $resolvedDataDir = [System.IO.Path]::GetFullPath($DataDir)
} else {
    $resolvedDataDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
New-Item -ItemType Directory -Force -Path $resolvedDataDir | Out-Null

$frontendUrl = "http://127.0.0.1:$FrontendPort"
$backendUrl = "http://127.0.0.1:$BackendPort"
$env:AUDIT_DATA_DIR = $resolvedDataDir
$env:AUDIT_PORT = "$BackendPort"
$env:AUDIT_FRONTEND_PORT = "$FrontendPort"
$env:AUDIT_FRONTEND_ORIGIN = $frontendUrl
$env:AUDIT_SEED_SYNTHETIC = '1'

$backendOut = Join-Path $runtimeDir "backend-$BackendPort.out.log"
$backendErr = Join-Path $runtimeDir "backend-$BackendPort.err.log"
$frontendOut = Join-Path $runtimeDir "frontend-$FrontendPort.out.log"
$frontendErr = Join-Path $runtimeDir "frontend-$FrontendPort.err.log"

$backend = Start-Process -FilePath 'uv' -ArgumentList @('run', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") -WorkingDirectory $repoRoot -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList @('--prefix', 'frontend', 'run', 'dev', '--', '--port', "$FrontendPort") -WorkingDirectory $repoRoot -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -WindowStyle Hidden -PassThru

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($backend.HasExited) { throw "Backend failed to start. See $backendErr" }
        if ($frontend.HasExited) { throw "Frontend failed to start. See $frontendErr" }
        try {
            $health = Invoke-RestMethod -Uri "$backendUrl/health" -TimeoutSec 1
            $page = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 1
            if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) { throw 'Local services did not become ready within 20 seconds.' }
    Write-Host "Hengjian Audit Workbench is ready: $frontendUrl"
    Write-Host 'Press Ctrl+C to stop both services.'
    if (-not $NoOpen) { Start-Process $frontendUrl }
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Seconds 1 }
} finally {
    foreach ($process in @($frontend, $backend)) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
}
