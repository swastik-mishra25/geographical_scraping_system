import os
from dotenv import load_dotenv

load_dotenv()

# General crawler configuration
USER_AGENT = os.getenv(
    "USER_AGENT",
    "GeographicalLeadScraperPOC/1.0 (contact: research@dakini.ai)",
)

REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "10000"))

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}

# 1. OpenStreetMap Overpass API
OVERPASS_URL = os.getenv(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
)
OVERPASS_TIMEOUT_SECONDS = int(os.getenv("OVERPASS_TIMEOUT_SECONDS", "8"))
OVERPASS_FALLBACK_URLS = [
    url.strip()
    for url in os.getenv(
        "OVERPASS_FALLBACK_URLS",
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter",
    ).split(",")
    if url.strip()
]
OSM_FALLBACK_DATASET_PATH = os.getenv(
    "OSM_FALLBACK_DATASET_PATH",
    "data/external/osm/indian_osm_agencies.json",
).strip()

# 2. Overture Maps (Remote GeoParquet via DuckDB)
OVERTURE_ENABLED = (
    os.getenv("OVERTURE_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
OVERTURE_MAX_ROWS = max(
    100, int(os.getenv("OVERTURE_MAX_ROWS", "10000"))
)
OVERTURE_TIMEOUT_SECONDS = int(os.getenv("OVERTURE_TIMEOUT_SECONDS", "45"))

# 3. Web Search Discovery (SearXNG with automated Open Web / MediaWiki fallback)
SEARXNG_URL = os.getenv(
    "SEARXNG_URL", "http://localhost:8080"
).rstrip("/")
SEARXNG_MAX_REQUESTS = max(
    1, int(os.getenv("SEARXNG_MAX_REQUESTS", "6"))
)
SEARXNG_TIMEOUT_SECONDS = int(os.getenv("SEARXNG_TIMEOUT_SECONDS", "8"))
SEARXNG_FALLBACK_TO_WEB = (
    os.getenv("SEARXNG_FALLBACK_TO_WEB", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

# Optional SerpApi integration
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()

# 4. Wikidata Query Service & Web API
WIKIDATA_ENABLED = (
    os.getenv("WIKIDATA_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
WIKIDATA_SPARQL_URL = os.getenv(
    "WIKIDATA_SPARQL_URL",
    "https://query.wikidata.org/sparql",
)
WIKIDATA_API_URL = os.getenv(
    "WIKIDATA_API_URL",
    "https://www.wikidata.org/w/api.php",
)
WIKIDATA_MAX_SEARCHES = max(
    1, min(10, int(os.getenv("WIKIDATA_MAX_SEARCHES", "4")))
)
WIKIDATA_TIMEOUT_SECONDS = int(os.getenv("WIKIDATA_TIMEOUT_SECONDS", "10"))

# 5. India Open Government Data: MCA Company Master Data
MCA_ENABLED = (
    os.getenv("MCA_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
MCA_DATASET_PATH = os.getenv(
    "MCA_DATASET_PATH",
    "data/external/company_master_data.csv",
).strip()

# 6. AllThePlaces / Agency Location Discovery (Local GeoJSON POIs or published extracts)
ALLTHEPLACES_ENABLED = (
    os.getenv("ALLTHEPLACES_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
ALLTHEPLACES_DATASET_PATH = os.getenv(
    "ALLTHEPLACES_DATASET_PATH",
    "data/external/alltheplaces",
).strip()
ALLTHEPLACES_TIMEOUT_SECONDS = int(os.getenv("ALLTHEPLACES_TIMEOUT_SECONDS", "10"))

# 7. Web Archive Corroboration (Wayback Machine CDX API + Common Crawl fallback)
WAYBACK_ENABLED = (
    os.getenv("WAYBACK_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
COMMONCRAWL_ENABLED = (
    os.getenv("COMMONCRAWL_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
COMMONCRAWL_INDEX_URL = os.getenv(
    "COMMONCRAWL_INDEX_URL",
    "https://index.commoncrawl.org/collinfo.json",
)
COMMONCRAWL_MAX_CHECKS = max(
    1, min(50, int(os.getenv("COMMONCRAWL_MAX_CHECKS", "20")))
)
COMMONCRAWL_TIMEOUT_SECONDS = int(os.getenv("COMMONCRAWL_TIMEOUT_SECONDS", "5"))
