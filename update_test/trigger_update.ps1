# trigger_update.ps1

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$current = Join-Path $dir 'TestApp.exe'
$pending = Join-Path $dir 'TestApp_update.exe'
$old     = $current + '.old'
$swap_ps = Join-Path $dir 'swap.ps1'
$log     = Join-Path $dir 'swap_log.txt'

if (-not (Test-Path $current)) { Write-Host 'TestApp.exe not found.' -ForegroundColor Red; exit 1 }
if (-not (Test-Path $pending)) { Write-Host 'TestApp_update.exe not found. Reset first.' -ForegroundColor Red; exit 1 }

$procs = Get-Process -Name 'TestApp' -ErrorAction SilentlyContinue
if (-not $procs) { Write-Host 'TestApp.exe is not running. Launch it first.' -ForegroundColor Red; Read-Host 'Press Enter'; exit 1 }

Write-Host "TestApp running ($($procs.Count) process(es)). Launching swap..." -ForegroundColor Cyan

$lines = @(
    "`$current = '$($current -replace "'","''")'",
    "`$pending = '$($pending -replace "'","''")'",
    "`$old     = '$($old -replace "'","''")'",
    "`$log     = '$($log -replace "'","''")'",
    "",
    "Add-Content `$log `"[`$(Get-Date -Format 'HH:mm:ss')] Swap started. Waiting for move to succeed...`"",
    "",
    "`$deadline = (Get-Date).AddSeconds(60)",
    "`$moved = `$false",
    "while (-not `$moved -and (Get-Date) -lt `$deadline) {",
    "    try {",
    "        if (Test-Path `$old) { Remove-Item `$old -Force -ErrorAction Stop }",
    "        Move-Item -Path `$current -Destination `$old -Force -ErrorAction Stop",
    "        `$moved = `$true",
    "    } catch {",
    "        Start-Sleep -Milliseconds 500",
    "    }",
    "}",
    "",
    "if (-not `$moved) { Add-Content `$log 'TIMED OUT waiting to move exe'; exit 1 }",
    "",
    "Add-Content `$log `"[`$(Get-Date -Format 'HH:mm:ss')] Old exe moved. Putting new exe in place...`"",
    "",
    "try {",
    "    Move-Item -Path `$pending -Destination `$current -Force -ErrorAction Stop",
    "    Add-Content `$log `"[`$(Get-Date -Format 'HH:mm:ss')] SWAP DONE. Relaunching...`"",
    "    Start-Process -FilePath `$current",
    "} catch {",
    "    Add-Content `$log `"[`$(Get-Date -Format 'HH:mm:ss')] SWAP FAILED: `$_`"",
    "}"
)
$lines | Set-Content -Path $swap_ps -Encoding UTF8

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName        = 'powershell.exe'
$psi.Arguments       = "-NonInteractive -ExecutionPolicy Bypass -File `"$swap_ps`""
$psi.CreateNoWindow  = $true
$psi.UseShellExecute = $false
[System.Diagnostics.Process]::Start($psi) | Out-Null

Write-Host 'Swap script running in background.' -ForegroundColor Green
Write-Host 'Close the VERSION 1 window — it will relaunch as VERSION 2.' -ForegroundColor Yellow
Write-Host 'Check swap_log.txt for the log.' -ForegroundColor Gray
