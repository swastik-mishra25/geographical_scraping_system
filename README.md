# Geographical Lead Scraping & Qualification POC

A basic full-stack system demonstrating:

Geographic Target
→ Lead Criteria
→ Geographic Business Discovery
→ Relevance Filtering
→ Public Website Enrichment
→ Contact Validation
→ Lead Qualification
→ Deduplication
→ CSV Export

## Architecture

Frontend:
- Plain HTML/CSS/JavaScript
- Served by FastAPI

Backend:
- FastAPI
- OpenStreetMap Overpass API for geographic discovery
- Requests + BeautifulSoup for public website enrichment
- robots.txt check before website access
- Pydantic models
- CSV export

## Run

### 1. Create environment

Windows:

    python -m venv .venv
    .venv\Scripts\activate

Linux/macOS:

    python -m venv .venv
    source .venv/bin/activate

### 2. Install

    pip install -r requirements.txt

### 3. Configure

Copy:

    .env.example

to:

    .env

Set USER_AGENT to a descriptive value with a contact email.

### 4. Start

    uvicorn app.main:app --reload

Open:

    http://127.0.0.1:8000

## API

Health:

    GET /health

Scrape:

    POST /api/scrape

Example JSON:

    {
      "country": "India",
      "state": "Odisha",
      "city": "Bhubaneswar",
      "category": "Digital Marketing",
      "limit": 25
    }

## Output

CSV files are written to:

    data/

The exported fields are:

- company_name
- sector
- city
- state
- website
- phone
- email
- source
- contact_validation
- lead_quality_score
- score_reason

## Important POC limitations

OpenStreetMap business coverage and tagging are incomplete. A missing business does not mean
that the business does not exist.

The POC only works with public information. It does not:
- bypass logins
- bypass CAPTCHAs
- access private pages
- fabricate missing contact data
- attempt to defeat access controls

Website enrichment checks robots.txt before requesting public pages. Site-specific terms,
rate limits and applicable laws should also be respected.

## Next production steps

1. Add multiple configurable discovery adapters.
2. Add persistent database storage.
3. Add stronger company/domain deduplication.
4. Add crawl queues and retry/backoff.
5. Add structured evidence storage per field.
6. Add configurable ICP scoring rules.
7. Add job status/progress tracking.
8. Add authentication and audit logging.
9. Add export formats beyond CSV.
10. Add stronger business-category verification.
