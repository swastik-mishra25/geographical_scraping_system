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


class NoCacheStaticFiles(StaticFiles):
    """Static file handler that enforces immediate cache revalidation in browsers."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.mount(
    "/static",
    NoCacheStaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.get("/")
def home():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


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
            phone_required=request.phone_required or request.phone_only,
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
def download_companies_csv(city: str = ""):
    """Download companies as CSV file, optionally filtered by desired location."""
    clean_city = city.strip()
    if clean_city:
        from app.services.exporter import export_csv
        import sqlite3
        from app.config import DATABASE_PATH
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM companies WHERE LOWER(city) = LOWER(?) ORDER BY (phone != '') DESC, updated_at DESC",
                (clean_city,),
            ).fetchall()
            leads = [dict(r) for r in rows]
            slug = clean_city.lower().replace(" ", "_")
            out_path = DATA_DIR / f"{slug}_companies_leads.csv"
            export_csv(leads, out_path.name)
            return FileResponse(
                out_path,
                media_type="text/csv",
                filename=f"{slug}_companies_leads.csv",
            )
        finally:
            conn.close()

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


@app.get("/api/database/status")
def get_database_status():
    """Retrieve operational database status, connection metrics, and active provider."""
    from app.config import DATABASE_PATH, USE_SUPABASE, SUPABASE_URL
    from app.services.supabase_client import SUPABASE_CLIENT
    
    supabase_test = SUPABASE_CLIENT.test_connection()
    import sqlite3
    sqlite_ok = False
    sqlite_companies = 0
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            sqlite_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            sqlite_ok = True
    except Exception:
        pass

    active_provider = "supabase" if (USE_SUPABASE and supabase_test.get("connected")) else "sqlite"

    return {
        "active_provider": active_provider,
        "supabase": {
            "enabled": USE_SUPABASE,
            "configured": SUPABASE_CLIENT.is_configured,
            "connected": supabase_test.get("connected", False),
            "project_url": SUPABASE_URL if SUPABASE_CLIENT.is_configured else None,
            "message": supabase_test.get("message", ""),
        },
        "sqlite": {
            "available": sqlite_ok,
            "database_path": DATABASE_PATH,
            "total_companies_preserved": sqlite_companies,
        },
    }


@app.get("/api/data/counts")
def get_database_counts(city: str = ""):
    """Return phone, qualified, and discovery record counts, optionally filtered by desired location."""
    import sqlite3
    from app.config import DATABASE_PATH
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        clean_city = city.strip()
        if clean_city:
            phone_count = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != '' AND LOWER(city) = LOWER(?)",
                (clean_city,),
            ).fetchone()[0]
            qualified_count = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE LOWER(city) = LOWER(?)",
                (clean_city,),
            ).fetchone()[0]
            discovery_count = conn.execute(
                """
                SELECT COUNT(DISTINCT d.url_id) 
                FROM discovered_urls d
                LEFT JOIN companies c ON d.normalized_url = c.website OR (c.website != '' AND instr(d.normalized_url, c.website) > 0)
                WHERE LOWER(c.city) = LOWER(?) OR LOWER(d.discovery_query) LIKE LOWER(?)
                """,
                (clean_city, f"%{clean_city}%"),
            ).fetchone()[0]
            if discovery_count < qualified_count:
                discovery_count = qualified_count
        else:
            phone_count = conn.execute("SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''").fetchone()[0]
            qualified_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            discovery_count = conn.execute("SELECT COUNT(*) FROM discovered_urls").fetchone()[0]

        return {
            "city": clean_city,
            "phone_leads": phone_count,
            "qualified_companies": qualified_count,
            "discovery_records": discovery_count,
        }
    finally:
        conn.close()


@app.get("/api/data/qualified")
@app.get("/api/data/qualified-companies")
def get_database_qualified(
    city: str = "",
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Retrieve qualified leads from SQLite, optionally filtered by desired location."""
    int_limit = getattr(limit, "default", limit)
    try:
        int_limit = int(int_limit)
    except (ValueError, TypeError):
        int_limit = 1000

    import sqlite3
    from app.config import DATABASE_PATH
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        clean_city = city.strip()
        if clean_city:
            rows = conn.execute(
                "SELECT * FROM companies WHERE LOWER(city) = LOWER(?) ORDER BY (phone != '') DESC, updated_at DESC LIMIT ?",
                (clean_city, int_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM companies ORDER BY updated_at DESC LIMIT ?",
                (int_limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/data/discovery")
@app.get("/api/data/discovery-candidates")
def get_database_discovery(
    city: str = "",
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Retrieve discovery candidates and crawl diagnostics from SQLite, optionally filtered by desired location."""
    int_limit = getattr(limit, "default", limit)
    try:
        int_limit = int(int_limit)
    except (ValueError, TypeError):
        int_limit = 1000

    import sqlite3
    from app.config import DATABASE_PATH
    from export_db_to_excel import get_all_discovery_data
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        headers, rows = get_all_discovery_data(conn)
        items = [dict(zip(headers, r)) for r in rows]
        clean_city = city.strip().lower()
        if clean_city:
            filtered = []
            for it in items:
                v_city = (it.get("verified_city") or "").lower()
                q = (it.get("discovery_query") or "").lower()
                if clean_city in v_city or clean_city in q:
                    filtered.append(it)
            return filtered[:int_limit]
        return items[:int_limit]
    finally:
        conn.close()


@app.get("/api/data/phone-leads")
def get_database_phone_leads(
    city: str = "",
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Retrieve verified leads that have available phone numbers from SQLite."""
    int_limit = getattr(limit, "default", limit)
    try:
        int_limit = int(int_limit)
    except (ValueError, TypeError):
        int_limit = 1000

    from app.services.persistence import get_companies_with_phone
    return get_companies_with_phone(city=city, limit=int_limit)


@app.get("/api/export/phone-leads")
def download_phone_leads_csv(city: str = ""):
    """Download CSV file containing verified leads with phone numbers, optionally filtered by location."""
    clean_city = city.strip()
    if clean_city:
        from app.services.exporter import export_csv
        from app.services.persistence import get_companies_with_phone
        leads = get_companies_with_phone(city=clean_city, limit=5000)
        slug = clean_city.lower().replace(" ", "_")
        out_path = DATA_DIR / f"{slug}_leads_with_phone.csv"
        export_csv(leads, out_path.name)
        return FileResponse(
            out_path,
            media_type="text/csv",
            filename=f"{slug}_leads_with_phone.csv",
        )

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




