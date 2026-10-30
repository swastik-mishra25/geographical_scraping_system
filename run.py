"""Application runner for Dakini Geographical Lead Discovery & Qualification POC.

Usage:
    .venv\\Scripts\\python run.py             (Starts with live reload restricted to 'app')
    .venv\\Scripts\\python run.py --no-reload (Starts without file reload for long scrapes)
"""
import os
import sys
import warnings

# Suppress known Pydantic V1 compat UserWarning on Python 3.14+
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module=r"fastapi\._compat\.v1",
)
warnings.filterwarnings(
    "ignore",
    message=r".*Core Pydantic V1 functionality isn't compatible.*",
)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    reload = "--no-reload" not in sys.argv

    print(f"\n=======================================================")
    print(f" Dakini AI - Geographical Lead Discovery & Qualification")
    print(f" URL: http://{host}:{port}")
    print(f" Mode: {'Auto-reload on app/ changes' if reload else 'Production (No reload)'}")
    print(f"=======================================================\n")

    try:
        if reload:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                reload=True,
                reload_dirs=["app"],
                log_level="info",
            )
        else:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                reload=False,
                log_level="info",
            )
    except KeyboardInterrupt:
        print("\n[server] Server stopped cleanly.")

