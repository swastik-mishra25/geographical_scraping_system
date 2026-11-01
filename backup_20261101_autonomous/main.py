import asyncio
from pathlib import Path
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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.models import ScrapeRequest, ScrapeResponse
from app.services.pipeline import run_pipeline


class GracefulCancellationMiddleware:
    """Intercept cancellations and keyboard interrupts so server shutdown/reload is clean."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except (asyncio.CancelledError, KeyboardInterrupt):
            # Cleanly absorb cancellation without logging raw ASGI exceptions
            pass


app = FastAPI(
    title="Geographical Lead Scraping POC",
    version="1.0.0",
    description=(
        "Public-data geographical business discovery, website enrichment, "
        "validation, qualification and CSV export."
    ),
)

app.add_middleware(GracefulCancellationMiddleware)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/scrape", response_model=ScrapeResponse)
def scrape(request: ScrapeRequest):
    try:
        result = run_pipeline(
            city=request.city,
            category=request.category,
            limit=request.limit,
            state=request.state,
        )
        return result
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get("/api/download")
def download_csv(path: str):
    file_path = Path(path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="CSV file not found")

    return FileResponse(
        file_path,
        media_type="text/csv",
        filename=file_path.name,
    )
