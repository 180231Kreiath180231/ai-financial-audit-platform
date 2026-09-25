param(
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [string]$CanaryIp = '192.0.2.1',
    [int]$CanaryPort = 9,
    [int]$Attempts = 10,
    [switch]$ConfirmNoExistingPktmonSession,
    [switch]$ConfirmNoExistingPktmonFilters
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([IO.Path]::IsPathRooted($Output)) {
    $resolvedOutput = [IO.Path]::GetFullPath($Output)
} else {
    $resolvedOutput = [IO.Path]::GetFullPath((Join-Path $repoRoot $Output))
}
$outputParent = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
$runId = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$runRoot = Join-Path $repoRoot ".runtime\offline-network-$runId"
New-Item -ItemType Directory -Path $runRoot | Out-Null

function Write-Result([System.Collections.IDictionary]$Value) {
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($resolvedOutput, $json + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output $json
}

function Invoke-AppLayerExercise([string]$TargetPath) {
    & uv run python scripts/measure_strict_offline_gateway.py exercise `
        --attempts $Attempts `
        --target-base-url "https://${CanaryIp}:$CanaryPort/v1" `
        --arm-network-canary `
        --output $TargetPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Strict-offline application exercise failed' }
    return Get-Content -LiteralPath $TargetPath -Raw | ConvertFrom-Json
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$os = Get-CimInstance Win32_OperatingSystem
$driver = Get-Service -Name pktmon -ErrorAction SilentlyContinue
$environment = [ordered]@{
    os_caption = $os.Caption
    os_version = $os.Version
    os_build = $os.BuildNumber
    architecture = $os.OSArchitecture
    administrator = $isAdministrator
    pktmon_path = (Get-Command pktmon.exe -ErrorAction SilentlyContinue).Source
    pktmon_driver_status = if ($driver) { [string]$driver.Status } else { 'not_found' }
}

$appLayerPath = Join-Path $runRoot 'app-layer.json'
if (-not $isAdministrator) {
    $appLayer = Invoke-AppLayerExercise $appLayerPath
    Write-Result ([ordered]@{
        scenario = 'windows-pktmon-strict-offline-v1'
        attempted_at = [DateTime]::UtcNow.ToString('o')
        status = 'blocked'
        reason = 'administrator_required_for_pktmon_driver'
        environment = $environment
        application_layer = $appLayer
        packet_capture = [ordered]@{
            status = 'not_executed'
            positive_control_packets = $null
            strict_offline_packets = $null
        }
        passed = $false
    })
    exit 2
}

if (-not $ConfirmNoExistingPktmonSession -or -not $ConfirmNoExistingPktmonFilters) {
    Write-Result ([ordered]@{
        scenario = 'windows-pktmon-strict-offline-v1'
        attempted_at = [DateTime]::UtcNow.ToString('o')
        status = 'blocked'
        reason = 'explicit_pktmon_state_confirmation_required'
        environment = $environment
        packet_capture = [ordered]@{ status = 'not_executed' }
        passed = $false
    })
    exit 2
}

$positiveEtl = Join-Path $runRoot 'positive-control.etl'
$positivePcap = Join-Path $runRoot 'positive-control.pcapng'
$positiveCount = Join-Path $runRoot 'positive-control-count.json'
$offlineEtl = Join-Path $runRoot 'strict-offline.etl'
$offlinePcap = Join-Path $runRoot 'strict-offline.pcapng'
$offlineCount = Join-Path $runRoot 'strict-offline-count.json'
$captureStarted = $false

function Start-PacketCapture([string]$TargetPath) {
    & pktmon start --capture --comp nics --type flow --pkt-size 128 --file-name $TargetPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PktMon failed to start: $LASTEXITCODE" }
    $script:captureStarted = $true
}

function Stop-PacketCapture {
    if ($script:captureStarted) {
        & pktmon stop | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "PktMon failed to stop: $LASTEXITCODE" }
        $script:captureStarted = $false
    }
}

try {
    & pktmon filter remove | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot clear confirmed-empty PktMon filters' }
    & pktmon filter add HengjianOfflineCanary -i $CanaryIp -t TCP SYN -p $CanaryPort | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot add PktMon canary filter' }

    Start-PacketCapture $positiveEtl
    $socket = [Net.Sockets.Socket]::new(
        [Net.Sockets.AddressFamily]::InterNetwork,
        [Net.Sockets.SocketType]::Stream,
        [Net.Sockets.ProtocolType]::Tcp
    )
    try {
        $connect = $socket.ConnectAsync([Net.IPAddress]::Parse($CanaryIp), $CanaryPort)
        [void]$connect.Wait(1000)
    } catch {
        # A connection failure is expected; only the outbound SYN is the positive control.
    } finally {
        $socket.Dispose()
    }
    Start-Sleep -Milliseconds 250
    Stop-PacketCapture
    & pktmon etl2pcap $positiveEtl --out $positivePcap | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot convert positive-control capture' }
    & uv run python scripts/measure_strict_offline_gateway.py count-pcap `
        --input $positivePcap --output $positiveCount
    if ($LASTEXITCODE -ne 0) { throw 'Cannot count positive-control packets' }

    Start-PacketCapture $offlineEtl
    $appLayer = Invoke-AppLayerExercise $appLayerPath
    Start-Sleep -Milliseconds 250
    Stop-PacketCapture
    & pktmon etl2pcap $offlineEtl --out $offlinePcap | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot convert strict-offline capture' }
    & uv run python scripts/measure_strict_offline_gateway.py count-pcap `
        --input $offlinePcap --output $offlineCount
    if ($LASTEXITCODE -ne 0) { throw 'Cannot count strict-offline packets' }

    $positive = Get-Content -LiteralPath $positiveCount -Raw | ConvertFrom-Json
    $offline = Get-Content -LiteralPath $offlineCount -Raw | ConvertFrom-Json
    $passed = $appLayer.passed -and $positive.packet_blocks -gt 0 -and $offline.packet_blocks -eq 0
    Write-Result ([ordered]@{
        scenario = 'windows-pktmon-strict-offline-v1'
        attempted_at = [DateTime]::UtcNow.ToString('o')
        status = if ($passed) { 'passed' } else { 'failed' }
        environment = $environment
        filter = [ordered]@{
            ip = $CanaryIp
            port = $CanaryPort
            protocol = 'TCP SYN'
        }
        application_layer = $appLayer
        packet_capture = [ordered]@{
            status = 'executed'
            positive_control = $positive
            strict_offline = $offline
            positive_control_sha256 = (Get-FileHash $positivePcap -Algorithm SHA256).Hash.ToLowerInvariant()
            strict_offline_sha256 = (Get-FileHash $offlinePcap -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        passed = $passed
    })
    if (-not $passed) { exit 1 }
} finally {
    if ($captureStarted) { & pktmon stop | Out-Null }
    & pktmon filter remove | Out-Null
}
