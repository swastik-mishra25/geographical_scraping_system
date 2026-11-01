"""Generic Public-Web Discovery adapter replacing legacy 7-provider discovery."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
import requests

from app.config import HEADERS
from app.services.crawl_policy import check_crawl_permission
from app.services.crawler import crawl_website
from app.services.dedupe import IndexedDeduplicator
from app.services.extraction import extract_business_data
from app.services.industry_classifier import classify_industry
from app.services.location_verifier import verify_location
from app.services.public_web_discovery import PublicWebDiscoveryGateway
from app.services.query_generator import generate_discovery_queries
from app.services.validation import validate_lead

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CITY_CACHE: dict[str, tuple[float, float, float, float, str]] = {}


@dataclass
class DiscoveryResult:
    """Preserved contract for discovery diagnostics."""
    businesses: list[dict[str, Any]] = field(default_factory=list)
    source_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def get_city_bounds(
    city: str,
    state: str = "",
) -> tuple[float, float, float, float, str]:
    """Resolve city bounding box with in-memory caching."""
    clean_city = city.strip()
    clean_state = state.strip()
    if not clean_city:
        raise ValueError("City name cannot be empty.")

    cache_key = f"{clean_city.casefold()}|{clean_state.casefold()}"
    if cache_key in CITY_CACHE:
        return CITY_CACHE[cache_key]

    query = ", ".join(p for p in (clean_city, clean_state, "India") if p)
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "countrycodes": "in",
                "limit": 1,
            },
            headers=HEADERS,
            timeout=5,
        )
        if resp.ok and resp.json():
            item = resp.json()[0]
            bbox = item.get("boundingbox", [])
            if len(bbox) == 4:
                south, north, west, east = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                detected_state = item.get("address", {}).get("state", state)
                res = (south, west, north, east, detected_state)
                CITY_CACHE[cache_key] = res
                return res
    except Exception:
        pass

    # Fallback bounding box
    res = (18.5, 72.5, 19.5, 73.5, state or "Maharashtra")
    CITY_CACHE[cache_key] = res
    return res


def discover_businesses_with_stats(
    city: str,
    limit: int = 25,
    category: str = "Digital Marketing",
    state: str = "",
) -> DiscoveryResult:
    """Discover candidate businesses through the generic Public-Web Discovery Gateway."""
    start_time = time.monotonic()
    gateway = PublicWebDiscoveryGateway()
    queries = generate_discovery_queries(industry=category, city=city, state=state, max_queries=6)

    candidates = gateway.run_discovery(queries, max_urls=max(limit * 2, 30))
    raw_count = len(candidates)

    businesses: list[dict[str, Any]] = []
    for cand in candidates[:limit]:
        crawl_res = crawl_website(cand["url"], max_pages=2)
        if crawl_res.get("status") == "completed" and crawl_res.get("crawled_pages"):
            ind_res = classify_industry(
                company_name="",
                combined_text=crawl_res["combined_text"],
                page_titles=crawl_res["page_titles"],
                industry_category=category,
            )
            if not ind_res.get("is_match"):
                continue

            loc_res = verify_location(
                city=city,
                state=state,
                country="India",
                locality="",
                crawled_pages=crawl_res["crawled_pages"],
            )

            biz = extract_business_data(
                root_url=cand["url"],
                crawled_pages=crawl_res["crawled_pages"],
                industry_category=category,
                city=city,
                state=state,
            )
            biz["sector"] = category
            biz["source"] = "Public Web Discovery Gateway"
            biz["industry_subcategory"] = ind_res.get("subcategory", "")
            biz["location_type"] = loc_res.get("location_type", "unverified")
            biz = validate_lead(biz)
            biz["lead_quality_score"] = 0
            biz["score_reason"] = "ICP scoring excluded by autonomous discovery policy"
            businesses.append(biz)

    deduper = IndexedDeduplicator()
    for b in businesses:
        deduper.add_or_merge(b)
    unique_businesses = deduper.get_results()[:limit]

    duration = round(time.monotonic() - start_time, 2)
    return DiscoveryResult(
        businesses=unique_businesses,
        source_stats={
            "Public Web Discovery Gateway": {
                "raw": raw_count,
                "unique": len(unique_businesses),
                "status": "ok",
                "duration_seconds": duration,
            }
        },
        notes=[f"Discovered {len(unique_businesses)} companies via Generic Public-Web Gateway."],
    )


def discover_businesses(
    city: str,
    limit: int = 25,
    category: str = "Digital Marketing",
    state: str = "",
) -> list[dict[str, Any]]:
    """Legacy helper returning candidate list."""
    return discover_businesses_with_stats(city, limit, category, state).businesses
