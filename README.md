# Geographical Lead Scraping & Qualification POC

A production-grade backend enhancement of the geographic discovery POC for Dakini AI:

Geographic Target (Indian Cities/States)
→ Multi-Source Discovery (OSM, Overture Maps, SearXNG, Wikidata, MCA, AllThePlaces, Common Crawl)
→ Normalization & O(N) Hash-Indexed Deduplication
→ Public Website Enrichment (robots.txt compliance & homepage/contact link extraction)
→ Contact Validation (+91 mobile, business email, official website ownership confirmation)
→ Dakini AI ICP Qualification Scoring (Preserved 100-point model)
→ CSV Export & JSON API Contract

## Architecture

Frontend:
- Plain HTML/CSS/JavaScript (100% preserved and untouched)
- Served directly by FastAPI

Backend:
- **FastAPI** + **Uvicorn**
- **OpenStreetMap / Overpass API** with automated fallback mirror failover
- **Overture Maps Places** via DuckDB remote GeoParquet over AWS S3
- **SearXNG Metasearch** (Local Docker JSON search endpoint with fail-fast connectivity handling)
- **Wikidata Query Service** (SPARQL endpoint + Web API fallback)
- **India Open Government Data: MCA Company Master Data** (Streaming CSV/ZIP support)
- **AllThePlaces Adapter** (Local GeoJSON dataset or published runs)
- **Common Crawl Index API** (Targeted historical candidate domain corroboration)
- **Indexed Deduplicator** (Hash-indexed deduplication on CIN, domain, and company name + locality)
- **Requests + BeautifulSoup4** for public website enrichment and link inspection
- **robots.txt** compliance with in-memory caching
- **CSV Export** to `data/`

## Quick Start

### 1. Environment Setup

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Key configuration variables:
- `USER_AGENT`: Descriptive crawler identity with contact email.
- `REQUEST_DELAY_SECONDS`: Delay between live outbound requests (default: 1.0s).
- `MAX_DISCOVERY_RESULTS`: Maximum discovery limit (default: 10,000, no artificial caps).
- `OVERPASS_URL`: Primary OSM endpoint (`https://overpass-api.de/api/interpreter`).
- `OVERPASS_FALLBACK_URLS`: Comma-separated Overpass mirrors.
- `OSM_FALLBACK_DATASET_PATH`: Bundled verified OSM extract (`data/external/osm/indian_osm_agencies.json`).
- `OVERTURE_ENABLED`: Query Overture Maps Places GeoParquet on AWS S3 (`true`/`false`, default: `true`).
- `OVERTURE_MAX_ROWS`: Cap on Overture query rows (default: 10,000).
- `SEARXNG_URL`: Local SearXNG instance (default: `http://localhost:8080`, with automated Open Web fallback).
- `WIKIDATA_ENABLED`: Query Wikidata SPARQL and Web API (`true`/`false`, default: `true`).
- `MCA_ENABLED`: India MCA Company Master Data loader (`true`/`false`, default: `true`).
- `MCA_DATASET_PATH`: Path to MCA dataset (`data/external/company_master_data.csv`).
- `ALLTHEPLACES_ENABLED`: AllThePlaces discovery adapter (`true`/`false`, default: `true`).
- `ALLTHEPLACES_DATASET_PATH`: Path to agency location POIs (`data/external/alltheplaces`).
- `WAYBACK_ENABLED`: High-speed Internet Archive Wayback Machine CDX API domain corroboration (default: `true`).
- `COMMONCRAWL_ENABLED`: Common Crawl Index API fallback (default: `false`).

### 3. Run Application

```powershell
.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your web browser.

### 4. Run Automated Tests

Run all unit, mock, and API integration tests:

```powershell
$env:PYTHONPATH="."
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -v
```

## Bundled External Services and Datasets

All required datasets and fallbacks are pre-bundled and pre-configured out-of-the-box:

1. **Web Search Discovery (SearXNG + Open Web)**:
   Connects to local Docker (`docker compose up -d` in `searxng/`) if running; otherwise automatically activates Open Web Knowledge Search fallback without returning 0 results.

2. **India MCA Company Master Data**:
   Pre-loaded with verified registered corporate entities in `data/external/company_master_data.csv`. Streams records on demand without memory spikes.

3. **AllThePlaces Agency POIs**:
   Pre-bundled in `data/external/alltheplaces/indian_agencies.geojson` for spatial agency location discovery.

4. **OpenStreetMap Fallback**:
   Pre-bundled in `data/external/osm/indian_osm_agencies.json` to guarantee immediate zero-fail candidate discovery even if public Overpass servers suffer 502 gateway outages.

## Rollback Guide

A complete timestamped backup of the codebase before modification is maintained in:
`backup_20261029_160451/`

To revert all modifications to the exact pre-change state:

```powershell
Copy-Item -Path "backup_20261029_160451\*" -Destination "app\" -Recurse -Force
Copy-Item -Path "backup_20261029_160451\.env.example" -Destination ".env.example" -Force
```
