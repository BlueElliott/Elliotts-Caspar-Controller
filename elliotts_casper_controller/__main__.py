import sys
import os
import multiprocessing

# In a windowed frozen exe (console=False) stdout/stderr are None.
# Python's logging module (and uvicorn) attach StreamHandlers to sys.stderr
# at import time — if it's None they crash silently and the web server never starts.
# Redirect to devnull before anything else is imported.
if getattr(sys, "frozen", False) and sys.platform == "win32":
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    multiprocessing.freeze_support()

    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Clean up leftovers from a previous auto-update
    try:
        exe_dir = os.path.dirname(sys.executable)
        for name in (sys.executable + ".old", os.path.join(exe_dir, "ElliottsCasparController_update.exe")):
            if os.path.exists(name):
                os.remove(name)
    except Exception:
        pass

from elliotts_casper_controller.gui_launcher import main

if __name__ == "__main__":
    main()
