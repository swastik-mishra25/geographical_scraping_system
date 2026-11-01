import asyncio
from pathlib import Path
import uuid
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

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import INDUSTRY_CONFIG
from app.models import ScrapeRequest, ScrapeResponse
from app.services.orchestrator import execute_autonomous_run
from app.services.persistence import (
    create_research_run,
    get_latest_checkpoint,
    get_research_run,
    list_research_runs,
)
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
    title="Dakini AI - Autonomous Public-Web Business Discovery System",
    version="2.0.0",
    description=(
        "Industry and Location-Driven Autonomous Public-Web Discovery, "
        "Crawling, Business Data Extraction and Validation System."
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


@app.get("/api/industries")
def get_industries():
    """Return all configured industry categories and their active/disabled status."""
    return [
        {
            "name": cfg["name"],
            "identifier": cfg["identifier"],
            "status": cfg["status"],
            "subcategories": cfg.get("subcategories", []),
        }
        for cfg in INDUSTRY_CONFIG.values()
    ]


@app.post("/api/scrape", response_model=ScrapeResponse)
def scrape(request: ScrapeRequest):
    """Primary web discovery endpoint maintaining backward-compatible response contract."""
    try:
        result = run_pipeline(
            city=request.city,
            category=request.category,
            limit=request.limit,
            state=request.state,
            country=request.country,
        )
        return result
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get("/api/runs")
def get_runs(limit: int = Query(default=20, ge=1, le=100)):
    """Retrieve history of autonomous research runs."""
    return list_research_runs(limit=limit)


@app.get("/api/runs/{run_id}")
def get_run_details(run_id: str):
    """Retrieve execution metrics and latest checkpoint for a research run."""
    run = get_research_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Research run '{run_id}' not found.")
    checkpoint = get_latest_checkpoint(run_id)
    return {
        "run": run,
        "latest_checkpoint": checkpoint,
    }


@app.post("/api/runs")
def queue_research_run(request: ScrapeRequest):
    """Queue an autonomous research run for independent background worker execution."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    run_record = create_research_run(
        run_id=run_id,
        industry=request.category,
        city=request.city,
        state=request.state,
        country=request.country,
        trigger_type="api_queue",
    )
    return {
        "status": "queued",
        "run_id": run_id,
        "details": run_record,
        "message": "Run queued successfully. The autonomous worker will process it independently of the UI.",
    }


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str):
    """Resume an interrupted or partially completed research run."""
    run = get_research_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Research run '{run_id}' not found.")
    if run.get("execution_status") == "completed":
        return {"status": "already_completed", "run_id": run_id}

    result = execute_autonomous_run(
        city=run["city"],
        category=run["industry"],
        state=run.get("state", ""),
        country=run.get("country", "India"),
        locality=run.get("locality", ""),
        run_id=run_id,
        trigger_type="api_resume",
    )
    return {
        "status": "resumed_and_completed",
        "run_id": run_id,
        "result": result,
    }


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


@app.get("/architecture")
def view_architecture():
    """Interactive architecture diagram viewer with one-click SVG/PNG export."""
    html_path = BASE_DIR.parent / "docs" / "architecture_diagram.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Architecture diagram HTML not found")
    return FileResponse(html_path, media_type="text/html")


@app.get("/architecture.svg")
@app.get("/api/architecture/diagram")
def download_architecture_diagram():
    """Download vector SVG architecture diagram."""
    svg_path = BASE_DIR.parent / "architecture_diagram.svg"
    if not svg_path.exists():
        raise HTTPException(status_code=404, detail="Architecture diagram SVG not found")
    return FileResponse(
        svg_path,
        media_type="image/svg+xml",
        filename="dakini_autonomous_architecture.svg",
    )

