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

    # Clean up any leftover .old exe from a previous auto-update
    try:
        old_exe = sys.executable + ".old"
        if os.path.exists(old_exe):
            os.remove(old_exe)
    except Exception:
        pass

from elliotts_casper_controller.gui_launcher import main

if __name__ == "__main__":
    main()
