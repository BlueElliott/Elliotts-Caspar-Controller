# trigger_update.ps1 — mirrors the swap logic in gui_launcher.py exactly

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$current = Join-Path $dir 'TestApp.exe'
$pending = Join-Path $dir 'TestApp_update.exe'
$old     = $current + '.old'
$swap_ps = Join-Path $dir 'swap.ps1'

if (-not (Test-Path $current)) { Write-Host 'TestApp.exe not found.' -ForegroundColor Red; exit 1 }
if (-not (Test-Path $pending)) { Write-Host 'TestApp_update.exe not found. Reset first.' -ForegroundColor Red; exit 1 }

$procs = Get-Process -Name 'TestApp' -ErrorAction SilentlyContinue
if (-not $procs) { Write-Host 'TestApp.exe is not running. Launch it first.' -ForegroundColor Red; Read-Host 'Press Enter'; exit 1 }

Write-Host "TestApp running ($($procs.Count) process(es)). Looking up _MEIPASS..." -ForegroundColor Cyan

# Find the _MEI extraction folder for the running TestApp.
# PyInstaller extracts to %TEMP%\_MEI<n> — find any _MEI folder whose content
# matches our exe (heuristic: look for python311.dll inside _MEI* folders).
$meipass = ''
$tempDir = [System.IO.Path]::GetTempPath()
$meiDirs = Get-ChildItem $tempDir -Filter '_MEI*' -Directory -ErrorAction SilentlyContinue |
           Where-Object { Test-Path (Join-Path $_.FullName 'python311.dll') } |
           Sort-Object LastWriteTime -Descending
if ($meiDirs) { $meipass = $meiDirs[0].FullName }
Write-Host "  _MEIPASS: $(if ($meipass) { $meipass } else { '(none found)' })" -ForegroundColor Gray

$lines = @(
    "`$current = '$($current -replace "'","''")'",
    "`$pending = '$($pending -replace "'","''")'",
    "`$old     = '$($old -replace "'","''")'",
    "`$meipass = '$($meipass -replace "'","''")'",
    "",
    "# Step 1: retry moving current -> old until exe file is released",
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
    "if (-not `$moved) { Remove-Item -Path `$pending -Force -ErrorAction SilentlyContinue; exit 1 }",
    "",
    "# Step 2: delete old _MEI folder so new exe always gets a clean extraction",
    "if (`$meipass -and (Test-Path `$meipass)) {",
    "    Remove-Item -Path `$meipass -Recurse -Force -ErrorAction SilentlyContinue",
    "}",
    "",
    "# Step 3: unblock + move new exe into place",
    "Unblock-File -Path `$pending -ErrorAction SilentlyContinue",
    "try {",
    "    Move-Item -Path `$pending -Destination `$current -Force -ErrorAction Stop",
    "} catch {",
    "    Move-Item -Path `$old -Destination `$current -Force -ErrorAction SilentlyContinue",
    "    exit 1",
    "}",
    "",
    "Start-Sleep -Seconds 2",
    "Start-Process -FilePath `$current",
    "`$dlDeadline = (Get-Date).AddSeconds(15)",
    "while ((Test-Path `$old) -and (Get-Date) -lt `$dlDeadline) {",
    "    try { Remove-Item -Path `$old -Force -ErrorAction Stop; break }",
    "    catch { Start-Sleep -Milliseconds 500 }",
    "}",
    "Remove-Item -Path `$MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue"
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
