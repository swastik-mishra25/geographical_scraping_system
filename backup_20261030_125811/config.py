import os
from dotenv import load_dotenv

load_dotenv()

# General crawler configuration
USER_AGENT = os.getenv(
    "USER_AGENT",
    "GeographicalLeadScraperPOC/1.0 (contact: research@dakini.ai)",
)

REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "1.5"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "200"))

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
OVERPASS_TIMEOUT_SECONDS = int(os.getenv("OVERPASS_TIMEOUT_SECONDS", "45"))
OVERPASS_FALLBACK_URLS = [
    url.strip()
    for url in os.getenv(
        "OVERPASS_FALLBACK_URLS",
        "https://overpass.kumi.systems/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter",
    ).split(",")
    if url.strip()
]

# 2. Overture Maps
OVERTURE_ENABLED = (
    os.getenv("OVERTURE_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
OVERTURE_MAX_ROWS = max(
    100, int(os.getenv("OVERTURE_MAX_ROWS", "1500"))
)
OVERTURE_TIMEOUT_SECONDS = int(os.getenv("OVERTURE_TIMEOUT_SECONDS", "45"))

# 3. SearXNG Metasearch
SEARXNG_URL = os.getenv(
    "SEARXNG_URL", "http://localhost:8080"
).rstrip("/")
SEARXNG_MAX_REQUESTS = max(
    1, int(os.getenv("SEARXNG_MAX_REQUESTS", "6"))
)
SEARXNG_TIMEOUT_SECONDS = int(os.getenv("SEARXNG_TIMEOUT_SECONDS", "10"))

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
    1, min(5, int(os.getenv("WIKIDATA_MAX_SEARCHES", "2")))
)
WIKIDATA_TIMEOUT_SECONDS = int(os.getenv("WIKIDATA_TIMEOUT_SECONDS", "12"))

# 5. India Open Government Data: MCA Company Master Data (local dataset)
MCA_ENABLED = (
    os.getenv("MCA_ENABLED", "false")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
MCA_DATASET_PATH = os.getenv(
    "MCA_DATASET_PATH",
    "data/external/company_master_data.zip",
).strip()

# 6. AllThePlaces (local dataset or published run)
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
ALLTHEPLACES_RUN_URL = os.getenv(
    "ALLTHEPLACES_RUN_URL",
    "https://data.alltheplaces.org/runs/latest/output/",
).strip()
ALLTHEPLACES_TIMEOUT_SECONDS = int(os.getenv("ALLTHEPLACES_TIMEOUT_SECONDS", "10"))

# 7. Common Crawl (Index API candidate corroboration)
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
    1, min(20, int(os.getenv("COMMONCRAWL_MAX_CHECKS", "5")))
)
COMMONCRAWL_TIMEOUT_SECONDS = int(os.getenv("COMMONCRAWL_TIMEOUT_SECONDS", "8"))
