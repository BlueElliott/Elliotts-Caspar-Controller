# trigger_update.ps1 — simulates clicking "Install Update" in the real app

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$current = Join-Path $dir "TestApp.exe"
$pending = Join-Path $dir "TestApp_update.exe"
$old     = $current + ".old"
$swap_ps = Join-Path $dir "swap.ps1"

# Find the PARENT TestApp process (PyInstaller spawns children — we want the top one)
$procs = Get-Process -Name "TestApp" -ErrorAction SilentlyContinue
if (-not $procs) {
    Write-Host "TestApp.exe is not running. Launch it first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Pick the process whose parent is NOT also a TestApp (i.e. the root process)
$procIds = $procs.Id
$pid_to_wait = ($procs | Where-Object {
    $parentId = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").ParentProcessId
    $parentId -notin $procIds
} | Select-Object -First 1).Id

if (-not $pid_to_wait) { $pid_to_wait = $procs[0].Id }

Write-Host "Found TestApp root PID: $pid_to_wait" -ForegroundColor Cyan
Write-Host "Launching background swap script..." -ForegroundColor Cyan

$swap = @"
`$pid_to_wait = $pid_to_wait
`$pending = "$pending"
`$current = "$current"
`$old     = "$old"
`$log     = "$dir\swap_log.txt"

"[`$(Get-Date -Format 'HH:mm:ss')] Swap script started. Waiting for PID `$pid_to_wait..." | Out-File `$log -Encoding UTF8

`$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt `$deadline) {
    if (-not (Get-Process -Id `$pid_to_wait -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}

"[`$(Get-Date -Format 'HH:mm:ss')] PID gone. Pausing 2s for handle release..." | Add-Content `$log
Start-Sleep -Seconds 2

try {
    if (Test-Path `$old) { Remove-Item `$old -Force }
    Move-Item -Path `$current -Destination `$old -Force
    Move-Item -Path `$pending -Destination `$current -Force
    "[`$(Get-Date -Format 'HH:mm:ss')] SWAP DONE. Relaunching `$current..." | Add-Content `$log
    Start-Process -FilePath `$current
} catch {
    "[`$(Get-Date -Format 'HH:mm:ss')] SWAP FAILED: `$_" | Add-Content `$log
}
"@

$swap | Set-Content -Path $swap_ps -Encoding UTF8

$CREATE_NO_WINDOW = 0x08000000
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName  = "powershell.exe"
$psi.Arguments = "-NonInteractive -ExecutionPolicy Bypass -File `"$swap_ps`""
$psi.CreateNoWindow  = $true
$psi.UseShellExecute = $false
[System.Diagnostics.Process]::Start($psi) | Out-Null

Write-Host "Done. Now CLOSE the VERSION 1 window." -ForegroundColor Yellow
Write-Host "TestApp.exe will relaunch as VERSION 2 automatically." -ForegroundColor Yellow
Write-Host "Check swap_log.txt for the full log." -ForegroundColor Gray
