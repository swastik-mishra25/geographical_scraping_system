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

from app.config import DATA_DIR, INDUSTRY_CONFIG
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
            phone_required=request.phone_required,
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


@app.get("/api/export/excel")
def download_excel_export():
    """Download the master database as a modern multi-sheet Excel spreadsheet (.xlsx)."""
    xlsx_path = DATA_DIR / "companies_leads.xlsx"
    if not xlsx_path.exists():
        # Trigger export if not present
        from export_db_to_excel import main as run_export
        run_export()
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail="No export data found.")
    return FileResponse(
        xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="dakini_master_leads_and_discovery.xlsx",
    )


@app.get("/api/export/discovery")
@app.get("/api/export/discovery/csv")
def download_discovery_csv():
    """Download all discovered candidate data as a universal CSV file."""
    csv_path = DATA_DIR / "all_discovery_data.csv"
    if not csv_path.exists():
        from export_db_to_excel import main as run_export
        run_export()
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="No discovery export data found.")
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename="dakini_all_discovery_data.csv",
    )


@app.get("/api/export/discovery/excel")
def download_discovery_excel():
    """Download the complete discovery dataset in multi-sheet Excel format."""
    xlsx_path = DATA_DIR / "all_discovery_data.xlsx"
    if not xlsx_path.exists():
        from export_db_to_excel import main as run_export
        run_export()
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail="No discovery export data found.")
    return FileResponse(
        xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="dakini_all_discovery_data.xlsx",
    )


@app.get("/api/export/companies")
def download_companies_csv():
    """Download the master companies database as a universal CSV file."""
    csv_path = DATA_DIR / "companies_leads.csv"
    if not csv_path.exists():
        from export_db_to_excel import main as run_export
        run_export()
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="No export data found.")
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename="dakini_companies_leads.csv",
    )


@app.get("/api/data/qualified")
def get_database_qualified():
    """Retrieve all qualified leads from the master SQLite database."""
    import sqlite3
    from app.config import DATABASE_PATH
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM companies ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/data/discovery")
def get_database_discovery():
    """Retrieve all discovery candidates and crawl diagnostics from SQLite."""
    import sqlite3
    from app.config import DATABASE_PATH
    from export_db_to_excel import get_all_discovery_data
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        headers, rows = get_all_discovery_data(conn)
        return [dict(zip(headers, r)) for r in rows]
    finally:
        conn.close()


@app.get("/api/data/phone-leads")
def get_database_phone_leads(
    city: str = "",
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Retrieve verified leads that have available phone numbers from SQLite."""
    from app.services.persistence import get_companies_with_phone
    return get_companies_with_phone(city=city, limit=limit)


@app.get("/api/export/phone-leads")
def download_phone_leads_csv():
    """Download CSV file containing only verified leads with available telephone numbers."""
    csv_path = DATA_DIR / "companies_with_phone.csv"
    if not csv_path.exists():
        from export_db_to_excel import main as run_export
        run_export()
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="No phone-verified leads export found.")
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename="dakini_leads_with_phone.csv",
    )


@app.get("/api/stats/phone")
def get_phone_coverage_stats():
    """Retrieve overall phone number coverage metrics across all discovered companies."""
    from app.services.persistence import get_phone_stats
    return get_phone_stats()


# =========================================================================
# Autonomous Self-Scraping Daemon Endpoints
# =========================================================================
@app.get("/api/autonomous/status")
def get_autonomous_status():
    """Check current status and real-time activity of the autonomous background scraping engine."""
    from app.services.autonomous_worker import AUTONOMOUS_ENGINE
    return AUTONOMOUS_ENGINE.get_status()


@app.post("/api/autonomous/start")
def start_autonomous_scraper(
    interval_seconds: int = Query(default=30, ge=10, le=3600),
    default_limit: int = Query(default=25, ge=5, le=500),
):
    """Start the autonomous self-scraping background daemon."""
    from app.services.autonomous_worker import AUTONOMOUS_ENGINE
    started = AUTONOMOUS_ENGINE.start(interval_seconds=interval_seconds, default_limit=default_limit)
    return {
        "status": "active" if started or AUTONOMOUS_ENGINE.is_active() else "failed",
        "message": "Autonomous self-scraping engine is running in the background." if started else "Autonomous engine is already active.",
        "config": {
            "interval_seconds": interval_seconds,
            "default_limit": default_limit,
        },
    }


@app.post("/api/autonomous/stop")
def stop_autonomous_scraper():
    """Stop the autonomous self-scraping background daemon."""
    from app.services.autonomous_worker import AUTONOMOUS_ENGINE
    stopped = AUTONOMOUS_ENGINE.stop()
    return {
        "status": "stopped",
        "message": "Autonomous self-scraping engine paused successfully." if stopped else "Autonomous engine was not running.",
    }


@app.post("/api/autonomous/sweep")
def trigger_autonomous_sweep(
    limit: int = Query(default=25, ge=5, le=200),
    background: bool = Query(default=False),
):
    """Run an autonomous multi-city sweep across major Indian business centers."""
    from app.services.autonomous_worker import AUTONOMOUS_ENGINE
    if background:
        import threading
        t = threading.Thread(
            target=AUTONOMOUS_ENGINE.run_sweep,
            kwargs={"limit_per_target": limit, "phone_required": True},
            daemon=True,
            name="DakiniSweepWorker",
        )
        t.start()
        return {
            "status": "started",
            "message": f"Autonomous multi-metro sweep started in background across {len(AUTONOMOUS_ENGINE._targets)} target business centers.",
            "targets_count": len(AUTONOMOUS_ENGINE._targets),
            "limit_per_target": limit,
        }
    return AUTONOMOUS_ENGINE.run_sweep(limit_per_target=limit, phone_required=True)




