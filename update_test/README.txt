AUTO-UPDATE TEST
================

Files in this folder:
  TestApp.exe          - The "installed" app (VERSION 1 - red text)
  TestApp_update.exe   - The "downloaded update" (VERSION 2 - green text)
  trigger_update.ps1   - Simulates clicking "Install Update" in the real app
  swap_log.txt         - Created after the test, shows what happened step by step

HOW TO TEST:
------------
1. Double-click TestApp.exe
   -> You should see a window saying VERSION 1 (red)

2. Right-click trigger_update.ps1 -> "Run with PowerShell"
   -> It finds the running TestApp.exe, launches the background swap script

3. Close the VERSION 1 window (or it closes automatically if the real app does os._exit)
   -> The swap script detects the process has gone

4. After ~2 seconds, TestApp.exe relaunches automatically
   -> It should now show VERSION 2 (green) - update successful!

5. Open swap_log.txt to see the full log of what happened.

WHAT THIS PROVES:
-----------------
- The swap script can wait for a frozen exe to exit
- It can rename the old exe and put the new one in its place
- It relaunches from the exact same path (so shortcuts still work)
- The same mechanism is used in the real ElliottsCasparController auto-update

TO RESET THE TEST:
------------------
- Delete TestApp.exe and TestApp.exe.old
- Copy TestApp_v1.exe -> TestApp.exe
- Copy TestApp_v2.exe -> TestApp_update.exe
