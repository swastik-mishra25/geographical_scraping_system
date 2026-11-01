import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# General crawler identity and compliance
USER_AGENT = os.getenv(
    "USER_AGENT",
    "DakiniPublicWebDiscovery/2.0 (+https://dakini.ai/bot; research@dakini.ai)",
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
}

# Central Database (SQLite via Python stdlib)
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    str(DATA_DIR / "dakini_discovery.db"),
)

# Autonomous Worker Controls
WORKER_POLL_INTERVAL_SECONDS = max(1, int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "3")))
WORKER_LOCK_FILE = os.getenv("WORKER_LOCK_FILE", str(DATA_DIR / "worker.lock"))
MAX_RUN_RETRIES = max(1, int(os.getenv("MAX_RUN_RETRIES", "3")))
CHECKPOINT_INTERVAL_ITEMS = max(1, int(os.getenv("CHECKPOINT_INTERVAL_ITEMS", "10")))

# Discovery Gateway Configuration (Generic Public Web Gateway)
DISCOVERY_MAX_QUERIES = max(1, int(os.getenv("DISCOVERY_MAX_QUERIES", "8")))
DISCOVERY_MAX_URLS = max(10, int(os.getenv("DISCOVERY_MAX_URLS", "250")))
DISCOVERY_TIMEOUT_SECONDS = float(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "8.0"))

# Crawler Policy & Safety (SSRF, robots, politeness)
ROBOTS_TIMEOUT_SECONDS = float(os.getenv("ROBOTS_TIMEOUT_SECONDS", "3.0"))
CRAWLER_MAX_DEPTH = max(1, int(os.getenv("CRAWLER_MAX_DEPTH", "2")))
CRAWLER_MAX_PAGES_PER_DOMAIN = max(1, int(os.getenv("CRAWLER_MAX_PAGES_PER_DOMAIN", "5")))
CRAWLER_REQUEST_DELAY_SECONDS = float(os.getenv("CRAWLER_REQUEST_DELAY_SECONDS", "0.2"))
CRAWLER_TIMEOUT_SECONDS = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "5.0"))
CRAWLER_MAX_CONCURRENCY = max(1, int(os.getenv("CRAWLER_MAX_CONCURRENCY", "12")))
CRAWLER_RESPECT_ROBOTS = os.getenv("CRAWLER_RESPECT_ROBOTS", "true").lower() in {"1", "true", "yes"}
SSRF_PROTECTED = os.getenv("SSRF_PROTECTED", "true").lower() in {"1", "true", "yes"}

# Preserved politeness delay alias
REQUEST_DELAY_SECONDS = CRAWLER_REQUEST_DELAY_SECONDS

# =========================================================================
# Industry Configuration Matrix (Section 4)
# =========================================================================
# The configuration supports 13 major industries; ONLY Digital Marketing is ACTIVE.
INDUSTRY_CONFIG = {
    "Digital Marketing": {
        "name": "Digital Marketing",
        "identifier": "digital_marketing",
        "status": "active",
        "subcategories": [
            "Digital Marketing Agencies",
            "SEO Agencies",
            "Search Engine Marketing",
            "Performance Marketing",
            "PPC Management",
            "Social Media Marketing",
            "Content Marketing",
            "Branding and Creative Agencies",
            "Online Advertising",
            "Lead Generation Agencies",
            "Growth Marketing",
            "Marketing Automation",
        ],
        "keywords": [
            "digital marketing",
            "seo agency",
            "search engine optimization",
            "performance marketing",
            "ppc management",
            "google ads",
            "social media marketing",
            "smm agency",
            "content marketing",
            "creative agency",
            "branding agency",
            "online advertising",
            "lead generation",
            "growth marketing",
            "marketing automation",
            "influencer marketing",
            "web design and marketing",
        ],
        "service_terms": [
            "search engine optimization",
            "pay-per-click",
            "ppc",
            "social media management",
            "content creation",
            "conversion rate optimization",
            "cro",
            "email marketing",
            "media buying",
            "brand strategy",
            "performance ads",
            "meta ads",
            "google adwords",
        ],
        "synonyms": [
            "digital agency",
            "marketing firm",
            "advertising agency",
            "growth agency",
            "digital studio",
        ],
        "query_templates": [
            "{subcategory} in {city}",
            "{keyword} agency in {city}",
            "{synonym} in {city} {state}",
            "{keyword} company in {city} {country}",
            "{keyword} in {locality} {city}",
        ],
        "exclusion_terms": [
            "course",
            "training institute",
            "certification",
            "syllabus",
            "internship",
            "job vacancy",
            "careers at",
            "blog post",
            "news article",
            "wikipedia",
            "directory listing",
        ],
    },
    "Healthcare": {
        "name": "Healthcare",
        "identifier": "healthcare",
        "status": "disabled",
        "subcategories": ["Hospitals", "Clinics", "Diagnostics", "Telehealth"],
        "keywords": ["hospital", "clinic", "healthcare", "diagnostic center"],
        "service_terms": ["consultation", "treatment", "diagnosis"],
        "synonyms": ["medical center", "nursing home"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Real Estate": {
        "name": "Real Estate",
        "identifier": "real_estate",
        "status": "disabled",
        "subcategories": ["Residential", "Commercial", "Brokers", "Property Management"],
        "keywords": ["real estate", "property developer", "realtor"],
        "service_terms": ["property sales", "leasing", "consulting"],
        "synonyms": ["realty", "builders"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Insurance": {
        "name": "Insurance",
        "identifier": "insurance",
        "status": "disabled",
        "subcategories": ["Life Insurance", "General Insurance", "Health Insurance"],
        "keywords": ["insurance broker", "insurance agency"],
        "service_terms": ["policy underwriting", "claims", "brokerage"],
        "synonyms": ["assurance"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Financial Services": {
        "name": "Financial Services",
        "identifier": "financial_services",
        "status": "disabled",
        "subcategories": ["Wealth Management", "Accounting", "Fintech", "Investment Banking"],
        "keywords": ["financial consultancy", "chartered accountants", "fintech"],
        "service_terms": ["tax consulting", "wealth advisory", "portfolio management"],
        "synonyms": ["finance firm", "advisory"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Education": {
        "name": "Education",
        "identifier": "education",
        "status": "disabled",
        "subcategories": ["Schools", "Colleges", "EdTech", "Coaching Institutes"],
        "keywords": ["school", "college", "edtech", "academy"],
        "service_terms": ["curriculum", "courses", "degrees"],
        "synonyms": ["institute", "university"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Hospitality": {
        "name": "Hospitality",
        "identifier": "hospitality",
        "status": "disabled",
        "subcategories": ["Hotels", "Resorts", "Restaurants", "Event Management"],
        "keywords": ["hotel", "resort", "restaurant", "catering"],
        "service_terms": ["lodging", "dining", "banquets"],
        "synonyms": ["hospitality suites", "inns"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "E-commerce": {
        "name": "E-commerce",
        "identifier": "ecommerce",
        "status": "disabled",
        "subcategories": ["D2C Brands", "Online Retailers", "Marketplaces"],
        "keywords": ["online store", "d2c brand", "ecommerce shop"],
        "service_terms": ["shipping", "catalog", "cart"],
        "synonyms": ["retailer", "web shop"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Manufacturing": {
        "name": "Manufacturing",
        "identifier": "manufacturing",
        "status": "disabled",
        "subcategories": ["Industrial", "Automotive", "Textiles", "Electronics"],
        "keywords": ["manufacturer", "factory", "industrial production"],
        "service_terms": ["oem", "fabrication", "assembly"],
        "synonyms": ["producers", "works"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Logistics": {
        "name": "Logistics",
        "identifier": "logistics",
        "status": "disabled",
        "subcategories": ["Freight Forwarding", "Warehousing", "Courier", "Cold Chain"],
        "keywords": ["logistics company", "freight forwarder", "transport service"],
        "service_terms": ["shipping", "cargo", "fleet"],
        "synonyms": ["supply chain firm", "movers"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Travel": {
        "name": "Travel",
        "identifier": "travel",
        "status": "disabled",
        "subcategories": ["Tour Operators", "Travel Agencies", "Corporate Travel"],
        "keywords": ["travel agency", "tour operator", "travel desk"],
        "service_terms": ["itineraries", "ticket bookings", "vacation packages"],
        "synonyms": ["trips", "travels"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "Business Services": {
        "name": "Business Services",
        "identifier": "business_services",
        "status": "disabled",
        "subcategories": ["Legal", "Consulting", "Staffing", "Facility Management"],
        "keywords": ["consulting firm", "staffing agency", "legal advisors"],
        "service_terms": ["advisory", "talent acquisition", "operations"],
        "synonyms": ["corporate services"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
    "SaaS / Technology": {
        "name": "SaaS / Technology",
        "identifier": "saas_technology",
        "status": "disabled",
        "subcategories": ["B2B SaaS", "Custom Software", "Cloud Infrastructure", "Cybersecurity"],
        "keywords": ["software company", "saas platform", "cloud services"],
        "service_terms": ["cloud migration", "api integration", "software development"],
        "synonyms": ["tech agency", "it solutions"],
        "query_templates": ["{keyword} in {city}"],
        "exclusion_terms": [],
    },
}

ACTIVE_INDUSTRY_IDENTIFIERS = {
    ident: cfg
    for ident, cfg in INDUSTRY_CONFIG.items()
    if cfg.get("status") == "active"
}


def get_industry_config(category_name: str) -> dict:
    """Return configuration for industry category or default to Digital Marketing."""
    for key, cfg in INDUSTRY_CONFIG.items():
        if key.lower() == (category_name or "").strip().lower() or cfg["identifier"] == (category_name or "").strip().lower():
            return cfg
    return INDUSTRY_CONFIG["Digital Marketing"]
