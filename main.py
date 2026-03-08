"""
main.py
-------
Entry point.  Run with:

    python main.py
    # or directly via uvicorn:
    uvicorn server.app:app --host 0.0.0.0 --port 8000

Then open http://localhost:8000 in your browser.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,   # reload=True is handy during dev but restarts the radar thread
        log_level="info",
    )
