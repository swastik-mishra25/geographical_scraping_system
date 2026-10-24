import os
from dotenv import load_dotenv

load_dotenv()

USER_AGENT = os.getenv(
    "USER_AGENT",
    "GeographicalLeadScraperPOC/1.0",
)

REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "1.5"))
MAX_DISCOVERY_RESULTS = int(os.getenv("MAX_DISCOVERY_RESULTS", "50"))

OVERPASS_URL = os.getenv(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}
# Optional SerpApi integration.
# Leave the API key blank to disable this source.
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()

SERPAPI_MAX_REQUESTS = max(
    1,
    int(os.getenv("SERPAPI_MAX_REQUESTS", "4")),
)