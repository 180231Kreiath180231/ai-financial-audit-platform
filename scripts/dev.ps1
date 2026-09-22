param(
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $repoRoot '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$env:AUDIT_DATA_DIR = Join-Path $repoRoot 'data\runtime'
$env:AUDIT_FRONTEND_ORIGIN = 'http://127.0.0.1:5173'
$env:AUDIT_SEED_SYNTHETIC = '1'

$backendOut = Join-Path $runtimeDir 'backend.out.log'
$backendErr = Join-Path $runtimeDir 'backend.err.log'
$frontendOut = Join-Path $runtimeDir 'frontend.out.log'
$frontendErr = Join-Path $runtimeDir 'frontend.err.log'

$backend = Start-Process -FilePath 'uv' -ArgumentList @('run', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $repoRoot -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList @('--prefix', 'frontend', 'run', 'dev') -WorkingDirectory $repoRoot -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -WindowStyle Hidden -PassThru

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($backend.HasExited) { throw "Backend failed to start. See $backendErr" }
        if ($frontend.HasExited) { throw "Frontend failed to start. See $frontendErr" }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 1
            $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1
            if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) { throw 'Local services did not become ready within 20 seconds.' }
    Write-Host 'Hengjian Audit Workbench is ready: http://127.0.0.1:5173'
    Write-Host 'Press Ctrl+C to stop both services.'
    if (-not $NoOpen) { Start-Process 'http://127.0.0.1:5173' }
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Seconds 1 }
} finally {
    foreach ($process in @($frontend, $backend)) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
}
