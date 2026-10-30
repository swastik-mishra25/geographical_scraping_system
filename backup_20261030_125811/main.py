from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import ScrapeRequest, ScrapeResponse
from app.services.pipeline import run_pipeline

app = FastAPI(
    title="Geographical Lead Scraping POC",
    version="1.0.0",
    description=(
        "Public-data geographical business discovery, website enrichment, "
        "validation, qualification and CSV export."
    ),
)

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
