$pid_to_wait = 4304
$pending = "C:\Users\ramdasse\Documents\Github\Elliott's Casper Controller\update_test\TestApp_update.exe"
$current = "C:\Users\ramdasse\Documents\Github\Elliott's Casper Controller\update_test\TestApp.exe"
$old     = "C:\Users\ramdasse\Documents\Github\Elliott's Casper Controller\update_test\TestApp.exe.old"
$log     = "C:\Users\ramdasse\Documents\Github\Elliott's Casper Controller\update_test\swap_log.txt"

"[$(Get-Date -Format 'HH:mm:ss')] Swap script started. Waiting for PID $pid_to_wait..." | Out-File $log -Encoding UTF8

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $pid_to_wait -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}

"[$(Get-Date -Format 'HH:mm:ss')] PID gone. Pausing 2s for handle release..." | Add-Content $log
Start-Sleep -Seconds 2

try {
    if (Test-Path $old) { Remove-Item $old -Force }
    Move-Item -Path $current -Destination $old -Force
    Move-Item -Path $pending -Destination $current -Force
    "[$(Get-Date -Format 'HH:mm:ss')] SWAP DONE. Relaunching $current..." | Add-Content $log
    Start-Process -FilePath $current
} catch {
    "[$(Get-Date -Format 'HH:mm:ss')] SWAP FAILED: $_" | Add-Content $log
}
