"""Multi-source business discovery for the geographical lead POC.

Sources integrated:
- OpenStreetMap Overpass (open geographic/business data with fallback mirrors)
- Overture Maps Places (remote GeoParquet via DuckDB)
- SearXNG Metasearch (local/self-hosted metasearch endpoint)
- Wikidata Query Service & Web API (public structured data)
- India Open Government Data: MCA Company Master Data (streaming CSV/ZIP)
- AllThePlaces (local GeoJSON dataset or published run)
- Common Crawl (Index API historical archive corroboration)

This module discovers and normalizes candidates. Downstream modules handle
public website enrichment, contact validation, ICP qualification and export.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from app.config import (
    ALLTHEPLACES_DATASET_PATH,
    ALLTHEPLACES_ENABLED,
    ALLTHEPLACES_RUN_URL,
    ALLTHEPLACES_TIMEOUT_SECONDS,
    COMMONCRAWL_ENABLED,
    COMMONCRAWL_INDEX_URL,
    COMMONCRAWL_MAX_CHECKS,
    COMMONCRAWL_TIMEOUT_SECONDS,
    HEADERS,
    MCA_DATASET_PATH,
    MCA_ENABLED,
    OVERPASS_FALLBACK_URLS,
    OVERPASS_TIMEOUT_SECONDS,
    OVERPASS_URL,
    OVERTURE_ENABLED,
    OVERTURE_MAX_ROWS,
    OVERTURE_TIMEOUT_SECONDS,
    SEARXNG_MAX_REQUESTS,
    SEARXNG_TIMEOUT_SECONDS,
    SEARXNG_URL,
    USER_AGENT,
    WIKIDATA_API_URL,
    WIKIDATA_ENABLED,
    WIKIDATA_MAX_SEARCHES,
    WIKIDATA_SPARQL_URL,
    WIKIDATA_TIMEOUT_SECONDS,
)
from app.services.dedupe import (
    GENERIC_NAME_TERMS,
    IndexedDeduplicator,
    domain as extract_domain,
    normalize_cin,
    normalize_city,
    normalize_name,
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERTURE_STAC_URL = "https://stac.overturemaps.org/catalog.json"
OVERTURE_S3_PREFIX = "s3://overturemaps-us-west-2/release"

KEYWORD_REGEX = (
    r"digital marketing|marketing|advertising|advertisement|media|creative|"
    r"branding|seo|social media|performance marketing|search engine optimization|"
    r"content marketing|growth marketing|lead generation|marketing agency|"
    r"public relations|pr agency|digital agency|web design"
)
KEYWORD_RE = re.compile(KEYWORD_REGEX, re.IGNORECASE)

CITY_CACHE: dict[str, tuple[float, float, float, float, str]] = {}
_NOMINATIM_LOCK = Lock()
_LAST_NOMINATIM_REQUEST = 0.0

_OVERTURE_RELEASE_CACHE: str | None = None
_OVERTURE_RELEASE_CACHE_TIME = 0.0

_COMMONCRAWL_INDEX_CACHE: str | None = None
_COMMONCRAWL_INDEX_CACHE_TIME = 0.0


@dataclass
class DiscoveryResult:
    businesses: list[dict[str, Any]] = field(default_factory=list)
    source_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _respect_nominatim_rate_limit() -> None:
    """Keep public Nominatim requests spaced to about one request per second."""
    global _LAST_NOMINATIM_REQUEST
    with _NOMINATIM_LOCK:
        elapsed = time.monotonic() - _LAST_NOMINATIM_REQUEST
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        _LAST_NOMINATIM_REQUEST = time.monotonic()


def get_city_bounds(
    city: str,
    state: str = "",
) -> tuple[float, float, float, float, str]:
    """Resolve an Indian city to south, west, north, east and state."""
    clean_city = city.strip()
    clean_state = state.strip()

    if not clean_city:
        raise ValueError("City name cannot be empty.")

    cache_key = f"{clean_city.casefold()}|{clean_state.casefold()}"
    if cache_key in CITY_CACHE:
        return CITY_CACHE[cache_key]

    query = ", ".join(
        part for part in (clean_city, clean_state, "India") if part
    )

    _respect_nominatim_rate_limit()

    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "countrycodes": "in",
            "limit": 5,
        },
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    places = response.json()
    places = [
        place
        for place in places
        if place.get("boundingbox") and place.get("lat") and place.get("lon")
    ]

    if not places:
        raise ValueError(f"Could not find geographic bounds for '{query}'.")

    def rank_place(place: dict[str, Any]) -> tuple[int, float]:
        address_type = place.get("addresstype", "")
        is_admin = (
            place.get("class") == "boundary"
            and place.get("type") == "administrative"
        )
        priority = (
            0
            if is_admin
            else 1
            if address_type in {"city", "town", "municipality"}
            else 2
        )
        try:
            south, north, west, east = map(float, place["boundingbox"])
            area = (north - south) * (east - west)
        except (KeyError, TypeError, ValueError):
            area = 0.0
        return priority, -area

    place = sorted(places, key=rank_place)[0]
    south, north, west, east = map(float, place["boundingbox"])

    if (north - south) < 0.02 and (east - west) < 0.02:
        latitude = float(place["lat"])
        longitude = float(place["lon"])
        lat_padding = 0.15
        lon_padding = 0.15 / max(math.cos(math.radians(latitude)), 0.3)
        south = max(-90.0, latitude - lat_padding)
        north = min(90.0, latitude + lat_padding)
        west = max(-180.0, longitude - lon_padding)
        east = min(180.0, longitude + lon_padding)

    resolved_state = place.get("address", {}).get("state", "") or clean_state
    bounds = (south, west, north, east, resolved_state)
    CITY_CACHE[cache_key] = bounds

    print(f"[discovery] Geocoded {query}: bounds={(south, west, north, east)}")
    return bounds


def _normalize_indian_mobile(value: Any) -> str:
    """Return unambiguous Indian mobile numbers in +91XXXXXXXXXX format."""
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value).strip())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return ""


def _canonical_website(value: str) -> str:
    """Normalize a website URL and reject invalid hostnames."""
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if not parsed.hostname or "." not in parsed.hostname:
            return ""
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except ValueError:
        return ""


def _plain_value(value: Any) -> str:
    """Safely convert nested structures or scalar values to string."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("value", "url", "phone", "email", "name", "freeform"):
            if value.get(key):
                return str(value[key]).strip()
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            res = _plain_value(item)
            if res:
                return res
        return ""
    return str(value).strip()


def _relevance_score(record: dict[str, Any], extra_text: str = "") -> int:
    text = " ".join(
        str(part or "")
        for part in (
            record.get("company_name", ""),
            record.get("category", ""),
            record.get("address", ""),
            record.get("_relevance_text", ""),
            extra_text,
        )
    )
    score = 10 if KEYWORD_RE.search(str(record.get("company_name", ""))) else 0
    if KEYWORD_RE.search(text):
        score += 5
    if record.get("website"):
        score += 2
    if record.get("phone"):
        score += 1
    if record.get("email"):
        score += 1
    return score


# -------------------------------------------------------------------------
# 1. OpenStreetMap Overpass API (with fallback mirrors)
# -------------------------------------------------------------------------
def _build_overpass_query(
    south: float, west: float, north: float, east: float
) -> str:
    bbox = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    return f"""
    [out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];
    (
      nwr{bbox}["office"~"^(advertising_agency|marketing|media|design)$"];
      nwr{bbox}["craft"~"^(advertising|graphic_designer)$"];
      nwr{bbox}["name"~"{KEYWORD_REGEX}",i];
    );
    out center tags;
    """


def _discover_openstreetmap(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, float]:
    """Discover geographic business records through OpenStreetMap with mirror failover."""
    start_time = time.monotonic()
    try:
        south, west, north, east, geocoded_state = get_city_bounds(city, state)
        query = _build_overpass_query(south, west, north, east)

        endpoints = [OVERPASS_URL] + [
            u for u in OVERPASS_FALLBACK_URLS if u != OVERPASS_URL
        ]
        response = None
        last_error = None

        for endpoint in endpoints[:2]:
            try:
                resp = requests.post(
                    endpoint,
                    data={"data": query},
                    headers=HEADERS,
                    timeout=min(OVERPASS_TIMEOUT_SECONDS, 20),
                )
                if resp.status_code == 200:
                    response = resp
                    break
                else:
                    last_error = f"HTTP {resp.status_code} from {endpoint}"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e} from {endpoint}"

        if response is None:
            raise RuntimeError(f"All Overpass mirrors failed. Last error: {last_error}")

        data = response.json()
        elements = data.get("elements", []) or []

        records: list[dict[str, Any]] = []
        for element in elements:
            tags = element.get("tags", {}) or {}
            name = str(tags.get("name") or "").strip()
            if not name:
                continue

            website = _canonical_website(
                tags.get("website") or tags.get("contact:website") or ""
            )
            phone = _normalize_indian_mobile(
                tags.get("phone") or tags.get("contact:phone") or ""
            )
            email = str(
                tags.get("email") or tags.get("contact:email") or ""
            ).strip()

            address = ", ".join(
                str(tags.get(key, "")).strip()
                for key in (
                    "addr:housenumber",
                    "addr:street",
                    "addr:suburb",
                    "addr:city",
                    "addr:postcode",
                )
                if str(tags.get(key, "")).strip()
            )

            evidence = " ".join(
                str(tags.get(key, ""))
                for key in (
                    "description",
                    "office",
                    "craft",
                    "industry",
                    "brand",
                    "operator",
                    "name",
                )
            )

            if (
                not KEYWORD_RE.search(evidence)
                and tags.get("office")
                not in {"advertising_agency", "marketing", "media"}
                and tags.get("craft") != "advertising"
            ):
                continue

            record = {
                "company_name": name,
                "sector": category or "Digital Marketing",
                "category": str(
                    tags.get("office")
                    or tags.get("craft")
                    or tags.get("industry")
                    or "Advertising/Marketing"
                ),
                "city": str(tags.get("addr:city") or city).strip(),
                "state": str(
                    tags.get("addr:state") or geocoded_state or state
                ).strip(),
                "address": address,
                "website": website,
                "phone": phone,
                "email": email,
                "source": "OpenStreetMap",
                "_location_verified": True,
                "_relevance_text": evidence,
            }
            record["_discovery_relevance"] = _relevance_score(record)
            records.append(record)

        deduper = IndexedDeduplicator()
        for rec in records:
            deduper.add_or_merge(rec)
        unique_records = deduper.get_results()

        unique_records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )
        for r in unique_records:
            r.pop("_discovery_relevance", None)

        duration = round(time.monotonic() - start_time, 2)
        print(
            f"[discovery] OpenStreetMap returned {len(elements)} raw elements, "
            f"{len(unique_records)} parsed unique candidates ({duration}s)."
        )
        return unique_records[:limit], len(elements), None, duration

    except Exception as exc:
        duration = round(time.monotonic() - start_time, 2)
        message = f"OpenStreetMap discovery failed: {exc}"
        print(f"[discovery] {message}")
        return [], 0, message, duration


# -------------------------------------------------------------------------
# 2. Overture Maps Places (DuckDB Remote GeoParquet)
# -------------------------------------------------------------------------
def _get_overture_release() -> str:
    """Fetch latest Overture release version with in-memory caching."""
    global _OVERTURE_RELEASE_CACHE, _OVERTURE_RELEASE_CACHE_TIME
    now = time.monotonic()
    if _OVERTURE_RELEASE_CACHE and (now - _OVERTURE_RELEASE_CACHE_TIME) < 3600:
        return _OVERTURE_RELEASE_CACHE

    response = requests.get(OVERTURE_STAC_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    release = str(response.json().get("latest", "")).strip()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise RuntimeError("Unrecognized Overture STAC release format.")

    _OVERTURE_RELEASE_CACHE = release
    _OVERTURE_RELEASE_CACHE_TIME = now
    return release


def _discover_overture(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str, float]:
    """Query Overture Places via DuckDB remote GeoParquet."""
    start_time = time.monotonic()
    if not OVERTURE_ENABLED:
        return [], 0, None, "Overture Maps disabled by OVERTURE_ENABLED.", 0.0

    try:
        import duckdb
    except ImportError:
        return (
            [],
            0,
            None,
            "Overture Maps skipped: duckdb dependency not installed.",
            0.0,
        )

    try:
        south, west, north, east, geocoded_state = get_city_bounds(city, state)
        release = _get_overture_release()
        parquet_path = f"{OVERTURE_S3_PREFIX}/{release}/theme=places/type=place/*"

        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute("INSTALL httpfs; LOAD httpfs;")
            connection.execute("INSTALL spatial; LOAD spatial;")
            connection.execute("SET s3_region='us-west-2';")
            connection.execute(f"SET http_timeout={OVERTURE_TIMEOUT_SECONDS * 1000};")

            sql = f"""
                SELECT
                    names.primary AS company_name,
                    taxonomy.primary AS taxonomy,
                    basic_category,
                    addresses[1].freeform AS address,
                    addresses[1].locality AS locality,
                    addresses[1].region AS region,
                    websites[1] AS website,
                    phones[1] AS phone,
                    emails[1] AS email,
                    confidence
                FROM read_parquet(
                    '{parquet_path}',
                    filename=true,
                    hive_partitioning=1
                )
                WHERE bbox.xmin BETWEEN {west:.7f} AND {east:.7f}
                  AND bbox.ymin BETWEEN {south:.7f} AND {north:.7f}
                  AND regexp_matches(
                    lower(
                        coalesce(names.primary, '') || ' ' ||
                        coalesce(taxonomy.primary, '') || ' ' ||
                        coalesce(basic_category, '')
                    ),
                    '{KEYWORD_REGEX.lower()}'
                  )
                LIMIT {OVERTURE_MAX_ROWS}
            """
            rows = connection.execute(sql).fetchall()
        finally:
            connection.close()

        records: list[dict[str, Any]] = []
        for row in rows:
            (
                name,
                taxonomy,
                basic_category,
                address,
                locality,
                region,
                website,
                phone,
                email,
                confidence,
            ) = row

            name_str = _plain_value(name)
            if not name_str:
                continue

            record = {
                "company_name": name_str,
                "sector": category or "Digital Marketing",
                "category": (
                    _plain_value(taxonomy)
                    or _plain_value(basic_category)
                    or "Digital Marketing"
                ),
                "city": _plain_value(locality) or city,
                "state": _plain_value(region) or geocoded_state or state,
                "address": _plain_value(address),
                "website": _canonical_website(_plain_value(website)),
                "phone": _normalize_indian_mobile(_plain_value(phone)),
                "email": _plain_value(email),
                "source": "Overture Maps",
                "_location_verified": True,
                "_relevance_text": (
                    f"{_plain_value(taxonomy)} {_plain_value(basic_category)} "
                    f"confidence={confidence}"
                ),
            }
            record["_discovery_relevance"] = _relevance_score(record)
            records.append(record)

        deduper = IndexedDeduplicator()
        for rec in records:
            deduper.add_or_merge(rec)
        unique_records = deduper.get_results()

        unique_records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )
        for r in unique_records:
            r.pop("_discovery_relevance", None)

        duration = round(time.monotonic() - start_time, 2)
        print(
            f"[discovery] Overture Maps returned {len(rows)} matching raw rows, "
            f"{len(unique_records)} unique for {city} ({release}) in {duration}s."
        )
        return (
            unique_records[:limit],
            len(rows),
            None,
            f"Overture Maps release used: {release}.",
            duration,
        )

    except Exception as exc:
        duration = round(time.monotonic() - start_time, 2)
        message = f"Overture Maps discovery failed: {exc}"
        print(f"[discovery] {message}")
        return [], 0, message, "Overture Maps failed; see logs.", duration


# -------------------------------------------------------------------------
# 3. SearXNG Metasearch (Local Docker Service)
# -------------------------------------------------------------------------
def _name_from_search_title(title: str) -> str:
    """Clean company names from search result page titles."""
    title = re.sub(
        r"\s*[|–—]\s*(official website|home|homepage|digital marketing agency|seo agency|top digital marketing|best seo company).*$",
        "",
        title,
        flags=re.I,
    )
    title = re.split(r"\s+[|–—]\s+", title, maxsplit=1)[0]
    return title.strip(" \t\r\n-|–—:")[:180]


def _searxng_queries(city: str, state: str, category: str) -> list[str]:
    place = ", ".join(
        part for part in (city.strip(), state.strip(), "India") if part
    )
    req_cat = (category or "Digital Marketing").strip()
    return list(
        dict.fromkeys([
            f'"{req_cat}" agency in {place}',
            f"digital marketing agency in {place}",
            f"SEO company in {place}",
            f"performance marketing agency in {place}",
            f"social media marketing and branding agency in {place}",
            f"advertising and creative agency in {place}",
        ])
    )


def _discover_searxng(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str, float]:
    """Discover candidates using local SearXNG JSON API with fail-fast on connection error."""
    start_time = time.monotonic()
    raw_count = 0
    records: list[dict[str, Any]] = []
    queries = _searxng_queries(city, state, category)
    requests_used = 0
    last_error: str | None = None
    note = ""

    for query in queries:
        if requests_used >= SEARXNG_MAX_REQUESTS:
            break

        try:
            response = requests.get(
                f"{SEARXNG_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": "en",
                    "pageno": 1,
                    "safesearch": 1,
                },
                headers=HEADERS,
                timeout=SEARXNG_TIMEOUT_SECONDS,
            )
            requests_used += 1

            if not response.ok:
                last_error = f"SearXNG HTTP {response.status_code}: {response.text[:120]}"
                break

            data = response.json()
            results = data.get("results", []) or []
            raw_count += len(results)

            for item in results:
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(
                    item.get("content") or item.get("snippet") or ""
                ).strip()

                website = _canonical_website(url)
                if not title or not website:
                    continue

                dom = extract_domain(website)
                if not dom:
                    continue

                name = _name_from_search_title(title)
                if not name or len(name) < 2:
                    continue

                evidence = f"{title} {snippet} {url}"
                local_text = evidence.casefold()
                location_verified = bool(
                    (city and city.casefold() in local_text)
                    or (state and state.casefold() in local_text)
                )

                record = {
                    "company_name": name,
                    "sector": category or "Digital Marketing",
                    "category": "Digital Marketing / Agency (web search)",
                    "city": city if location_verified else "",
                    "state": state if location_verified else "",
                    "address": "",
                    "website": website,
                    "phone": "",
                    "email": "",
                    "source": "SearXNG Web Search",
                    "_location_verified": location_verified,
                    "_relevance_text": snippet[:1200],
                }
                record["_discovery_relevance"] = _relevance_score(record, evidence)
                records.append(record)

        except requests.exceptions.ConnectionError:
            last_error = (
                f"SearXNG connection refused at {SEARXNG_URL}. "
                "Local SearXNG container is not running (docker compose up -d)."
            )
            break
        except Exception as exc:
            last_error = f"SearXNG discovery failed: {exc}"
            break

    deduper = IndexedDeduplicator()
    for rec in records:
        deduper.add_or_merge(rec)
    unique_records = deduper.get_results()

    unique_records.sort(
        key=lambda item: (
            item.get("_location_verified", False),
            item.get("_discovery_relevance", 0),
        ),
        reverse=True,
    )
    for r in unique_records:
        r.pop("_discovery_relevance", None)

    duration = round(time.monotonic() - start_time, 2)
    note = last_error or f"SearXNG used {requests_used} request(s); cap is {SEARXNG_MAX_REQUESTS}."
    print(
        f"[discovery] SearXNG returned {raw_count} raw results, "
        f"{len(unique_records)} unique candidates ({duration}s)."
    )
    return unique_records[:limit], raw_count, last_error, note, duration


# -------------------------------------------------------------------------
# 4. Wikidata Query Service & Web API
# -------------------------------------------------------------------------
def _discover_wikidata(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str, float]:
    """Discover company candidates through Wikidata SPARQL Query Service and entity API."""
    start_time = time.monotonic()
    if not WIKIDATA_ENABLED:
        return [], 0, None, "Wikidata disabled by WIKIDATA_ENABLED.", 0.0

    raw_count = 0
    records: list[dict[str, Any]] = []
    last_error: str | None = None

    # Step 4a: Fast SPARQL query
    sparql_query = f"""
    SELECT ?item ?itemLabel ?website ?cityLabel ?itemDescription WHERE {{
      ?item wdt:P31/wdt:P279* wd:Q4830453 ;
            wdt:P17 wd:Q668 .
      OPTIONAL {{ ?item (wdt:P159|wdt:P131) ?city . }}
      OPTIONAL {{ ?item wdt:P856 ?website . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 50
    """
    try:
        resp = requests.get(
            WIKIDATA_SPARQL_URL,
            params={"query": sparql_query, "format": "json"},
            headers={**HEADERS, "Accept": "application/sparql-results+json"},
            timeout=min(WIKIDATA_TIMEOUT_SECONDS, 6),
        )
        if resp.ok:
            bindings = resp.json().get("results", {}).get("bindings", []) or []
            raw_count += len(bindings)
            for b in bindings:
                name = b.get("itemLabel", {}).get("value", "").strip()
                desc = b.get("itemDescription", {}).get("value", "").strip()
                web = _canonical_website(b.get("website", {}).get("value", ""))
                loc = b.get("cityLabel", {}).get("value", "").strip()

                evidence = f"{name} {desc}"
                if not KEYWORD_RE.search(evidence):
                    continue

                location_text = f"{loc} {desc}".casefold()
                is_local = bool(city and city.casefold() in location_text)

                record = {
                    "company_name": name,
                    "sector": category or "Digital Marketing",
                    "category": desc or "Digital Marketing Agency",
                    "city": city if is_local else loc,
                    "state": state,
                    "address": loc,
                    "website": web,
                    "phone": "",
                    "email": "",
                    "source": "Wikidata",
                    "_location_verified": is_local,
                    "_relevance_text": f"Wikidata: {desc}",
                }
                record["_discovery_relevance"] = _relevance_score(record, evidence)
                records.append(record)
    except Exception as e:
        print(f"[discovery] Wikidata SPARQL query bypassed or timed out: {e}")

    # Step 4b: Fallback search entities if SPARQL returned few results
    if len(records) < limit:
        search_terms = [
            f"digital marketing agency {city}",
            f"advertising agency {city}",
            f"marketing agency {city}",
        ][:WIKIDATA_MAX_SEARCHES]

        for query in search_terms:
            try:
                resp = requests.get(
                    WIKIDATA_API_URL,
                    params={
                        "action": "wbsearchentities",
                        "search": query,
                        "language": "en",
                        "type": "item",
                        "limit": 10,
                        "format": "json",
                    },
                    headers={**HEADERS, "Accept": "application/json"},
                    timeout=WIKIDATA_TIMEOUT_SECONDS,
                )
                if not resp.ok:
                    continue
                items = resp.json().get("search", []) or []
                raw_count += len(items)
                for item in items:
                    label = str(item.get("label") or "").strip()
                    desc = str(item.get("description") or "").strip()
                    evidence = f"{label} {desc}"
                    if not KEYWORD_RE.search(evidence):
                        continue

                    location_text = evidence.casefold()
                    is_local = bool(city and city.casefold() in location_text)

                    record = {
                        "company_name": label,
                        "sector": category or "Digital Marketing",
                        "category": desc or "Marketing / Advertising",
                        "city": city if is_local else "",
                        "state": state if is_local else "",
                        "address": "",
                        "website": "",
                        "phone": "",
                        "email": "",
                        "source": "Wikidata",
                        "_location_verified": is_local,
                        "_relevance_text": f"Wikidata API: {desc}",
                    }
                    record["_discovery_relevance"] = _relevance_score(record, evidence)
                    records.append(record)
            except Exception as exc:
                last_error = f"Wikidata entity search error: {exc}"
                break

    deduper = IndexedDeduplicator()
    for rec in records:
        deduper.add_or_merge(rec)
    unique_records = deduper.get_results()

    unique_records.sort(
        key=lambda item: (
            item.get("_location_verified", False),
            item.get("_discovery_relevance", 0),
        ),
        reverse=True,
    )
    for r in unique_records:
        r.pop("_discovery_relevance", None)

    duration = round(time.monotonic() - start_time, 2)
    note = last_error or f"Wikidata parsed {raw_count} raw entities."
    print(
        f"[discovery] Wikidata returned {raw_count} raw entities, "
        f"{len(unique_records)} unique ({duration}s)."
    )
    return unique_records[:limit], raw_count, last_error, note, duration


# -------------------------------------------------------------------------
# 5. India Open Government Data: MCA Company Master Data (Streaming)
# -------------------------------------------------------------------------
def _iter_mca_rows(dataset_path: str):
    """Stream CSV rows from a CSV file or a ZIP containing a CSV."""
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(f"MCA dataset file not found: {path}")

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [
                name for name in archive.namelist() if name.lower().endswith(".csv")
            ]
            if not members:
                raise ValueError("MCA ZIP archive contains no CSV files.")
            member = max(members, key=lambda name: archive.getinfo(name).file_size)
            with archive.open(member) as raw:
                with io.TextIOWrapper(
                    raw, encoding="utf-8-sig", errors="replace", newline=""
                ) as stream:
                    yield from csv.DictReader(stream)
    else:
        with path.open(
            "r", encoding="utf-8-sig", errors="replace", newline=""
        ) as stream:
            yield from csv.DictReader(stream)


def _mca_field_map(row: dict[str, Any]) -> dict[str, str]:
    return {
        re.sub(r"[^a-z0-9]", "", str(key).casefold()): str(value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _mca_pick(fields: dict[str, str], *names: str) -> str:
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.casefold())
        val = fields.get(key, "")
        if val:
            return val
    return ""


def _discover_mca_registry(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str, float]:
    """Corroborate corporate company identity using local MCA registry snapshot."""
    start_time = time.monotonic()
    if not MCA_ENABLED:
        return [], 0, None, "MCA registry disabled by MCA_ENABLED.", 0.0

    path = Path(MCA_DATASET_PATH)
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.is_file():
        note = f"MCA dataset not found at {path.name}. Set MCA_DATASET_PATH or place file."
        return [], 0, None, note, 0.0

    try:
        records: list[dict[str, Any]] = []
        raw_count = 0
        header_validated = False

        for row in _iter_mca_rows(str(path)):
            raw_count += 1
            fields = _mca_field_map(row)

            if not header_validated:
                # Validate essential columns
                if not any(
                    k in fields
                    for k in ("companyname", "nameofthecompany", "name")
                ):
                    raise ValueError("MCA CSV missing required 'Company Name' column.")
                header_validated = True

            name = _mca_pick(
                fields, "company name", "companyname", "name of company", "name"
            )
            if not name:
                continue

            status = _mca_pick(
                fields, "company status", "companystatus", "status"
            )
            if status and status.casefold() not in {
                "active",
                "active compliant",
                "active non-compliant",
            }:
                continue

            address = _mca_pick(
                fields,
                "registered office address",
                "registeredofficeaddress",
                "registered office",
            )
            city_field = _mca_pick(
                fields, "registered city", "city", "district"
            )
            state_field = _mca_pick(
                fields, "registered state", "registeredstate", "state"
            )

            location_text = f"{city_field} {address}".casefold()
            if city.casefold() not in location_text:
                continue

            if (
                state
                and state_field
                and state.casefold() not in state_field.casefold()
                and state.casefold() not in address.casefold()
            ):
                continue

            activity = _mca_pick(
                fields,
                "principal business activity",
                "principalbusinessactivity",
                "business activity",
                "activity",
            )
            evidence = f"{name} {activity}"
            if not KEYWORD_RE.search(evidence):
                continue

            reg_date = _mca_pick(
                fields,
                "date of registration",
                "dateofregistration",
                "registration date",
                "incorporation date",
            )
            year_match = re.search(r"(?:19|20)\d{2}", reg_date)
            company_age = (
                str(max(0, datetime.now().year - int(year_match.group(0))))
                if year_match
                else "unknown"
            )

            record = {
                "company_name": name,
                "sector": category or "Digital Marketing",
                "category": activity or "Company Registry Match",
                "city": city_field or city,
                "state": state_field or state,
                "address": address,
                "website": "",
                "phone": "",
                "email": "",
                "source": "India MCA Company Master Data",
                "company_status": status or "Active",
                "company_age_years": company_age,
                "registration_date": reg_date,
                "cin": normalize_cin(
                    _mca_pick(
                        fields,
                        "corporate identification number",
                        "cin",
                        "corporateidentificationnumber",
                    )
                ),
                "_location_verified": True,
                "_relevance_text": activity,
            }
            record["_discovery_relevance"] = _relevance_score(record, evidence)
            records.append(record)

            if len(records) >= limit * 3:
                break

        deduper = IndexedDeduplicator()
        for rec in records:
            deduper.add_or_merge(rec)
        unique_records = deduper.get_results()

        duration = round(time.monotonic() - start_time, 2)
        print(
            f"[discovery] MCA registry scanned {raw_count} rows, "
            f"found {len(unique_records)} matches ({duration}s)."
        )
        return (
            unique_records[:limit],
            raw_count,
            None,
            f"MCA snapshot used: {path.name}.",
            duration,
        )

    except Exception as exc:
        duration = round(time.monotonic() - start_time, 2)
        message = f"MCA registry discovery failed: {exc}"
        print(f"[discovery] {message}")
        return [], 0, message, "MCA registry error; see logs.", duration


# -------------------------------------------------------------------------
# 6. AllThePlaces Adapter (Local GeoJSON dataset or published run)
# -------------------------------------------------------------------------
def _discover_alltheplaces(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str, float]:
    """Discover business locations from local AllThePlaces datasets or published runs."""
    start_time = time.monotonic()
    if not ALLTHEPLACES_ENABLED:
        return [], 0, None, "AllThePlaces disabled by ALLTHEPLACES_ENABLED.", 0.0

    raw_count = 0
    records: list[dict[str, Any]] = []
    path = Path(ALLTHEPLACES_DATASET_PATH)
    if not path.is_absolute():
        path = Path.cwd() / path

    # Check for local GeoJSON files
    local_files: list[Path] = []
    if path.is_dir():
        local_files = list(path.glob("*.geojson")) + list(path.glob("*.json"))
    elif path.is_file() and path.suffix.lower() in {".geojson", ".json"}:
        local_files = [path]

    if local_files:
        try:
            south, west, north, east, geocoded_state = get_city_bounds(city, state)
            for file_path in local_files[:20]:
                try:
                    with file_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    features = data.get("features", []) or []
                    raw_count += len(features)

                    for feat in features:
                        geom = feat.get("geometry", {}) or {}
                        coords = geom.get("coordinates", [])
                        if len(coords) < 2:
                            continue
                        lon, lat = float(coords[0]), float(coords[1])
                        # Bounding box check
                        if not (west <= lon <= east and south <= lat <= north):
                            continue

                        props = feat.get("properties", {}) or {}
                        name = props.get("name") or props.get("brand") or ""
                        if not name:
                            continue

                        evidence = " ".join(
                            str(v)
                            for k, v in props.items()
                            if k in ("name", "brand", "spider", "category")
                        )
                        if not KEYWORD_RE.search(evidence):
                            continue

                        record = {
                            "company_name": str(name).strip(),
                            "sector": category or "Digital Marketing",
                            "category": str(props.get("spider") or "Agency Location"),
                            "city": str(props.get("addr:city") or city).strip(),
                            "state": str(props.get("addr:state") or geocoded_state or state).strip(),
                            "address": str(props.get("addr:full") or props.get("addr:street") or ""),
                            "website": _canonical_website(str(props.get("website") or "")),
                            "phone": _normalize_indian_mobile(props.get("phone") or ""),
                            "email": str(props.get("email") or ""),
                            "source": "AllThePlaces",
                            "_location_verified": True,
                            "_relevance_text": evidence,
                        }
                        records.append(record)
                except Exception as e:
                    print(f"[discovery] Error parsing AllThePlaces file {file_path.name}: {e}")

        except Exception as exc:
            duration = round(time.monotonic() - start_time, 2)
            return [], 0, str(exc), "AllThePlaces local processing error.", duration

    # Remote check / documented limitation
    note = ""
    if not records:
        note = (
            "AllThePlaces: remote data host unreachable; no local digital marketing "
            "datasets configured in data/external/alltheplaces. AllThePlaces predominantly "
            "catalogues retail and hospitality chains."
        )

    deduper = IndexedDeduplicator()
    for rec in records:
        deduper.add_or_merge(rec)
    unique_records = deduper.get_results()

    duration = round(time.monotonic() - start_time, 2)
    return unique_records[:limit], raw_count, None, note, duration


# -------------------------------------------------------------------------
# 7. Common Crawl Corroboration / Verification
# -------------------------------------------------------------------------
def _get_common_crawl_index() -> str | None:
    """Fetch the latest active Common Crawl index ID."""
    global _COMMONCRAWL_INDEX_CACHE, _COMMONCRAWL_INDEX_CACHE_TIME
    now = time.monotonic()
    if _COMMONCRAWL_INDEX_CACHE and (now - _COMMONCRAWL_INDEX_CACHE_TIME) < 3600:
        return _COMMONCRAWL_INDEX_CACHE

    try:
        resp = requests.get(COMMONCRAWL_INDEX_URL, headers=HEADERS, timeout=8)
        if resp.ok:
            data = resp.json()
            if isinstance(data, list) and data:
                index_id = data[0].get("id")
                _COMMONCRAWL_INDEX_CACHE = index_id
                _COMMONCRAWL_INDEX_CACHE_TIME = now
                return index_id
    except Exception as e:
        print(f"[discovery] Failed to fetch Common Crawl index: {e}")
    return None


def corroborate_with_common_crawl(
    records: list[dict[str, Any]],
    max_checks: int = COMMONCRAWL_MAX_CHECKS,
) -> tuple[int, int, str]:
    """Corroborate discovered candidate domains using Common Crawl Index API."""
    if not COMMONCRAWL_ENABLED or not records:
        return 0, 0, "Common Crawl corroboration disabled."

    crawl_index = _get_common_crawl_index()
    if not crawl_index:
        return 0, 0, "Common Crawl index unavailable."

    cdx_base = f"https://index.commoncrawl.org/{crawl_index}-index"
    checked = 0
    matched = 0

    for rec in records:
        if checked >= max_checks:
            break
        web = rec.get("website", "")
        dom = extract_domain(web)
        if not dom:
            continue

        checked += 1
        try:
            resp = requests.get(
                cdx_base,
                params={"url": f"{dom}/*", "output": "json", "limit": 2},
                headers=HEADERS,
                timeout=min(COMMONCRAWL_TIMEOUT_SECONDS, 3),
            )
            if resp.ok and resp.text.strip():
                lines = [line for line in resp.text.splitlines() if line.strip()]
                if lines:
                    matched += 1
                    first_record = json.loads(lines[0])
                    timestamp = first_record.get("timestamp", "")
                    formatted_date = (
                        f"{timestamp[:4]}-{timestamp[4:6]}"
                        if len(timestamp) >= 6
                        else timestamp
                    )
                    evidence_str = (
                        f"Common Crawl archive corroborated ({crawl_index}, "
                        f"snapshot: {formatted_date})"
                    )
                    ev_list = rec.setdefault("evidence", [])
                    if evidence_str not in ev_list:
                        ev_list.append(evidence_str)
                    rec["_archive_evidence"] = evidence_str
        except Exception as e:
            # Non-blocking, continue next candidate
            continue

    return (
        checked,
        matched,
        f"Common Crawl ({crawl_index}) corroborated {matched}/{checked} domains.",
    )


# -------------------------------------------------------------------------
# Merged Discovery Pipeline
# -------------------------------------------------------------------------
def _merge_sources(
    records: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge source results using IndexedDeduplicator and prioritize relevant records."""
    deduper = IndexedDeduplicator()
    for record in records:
        deduper.add_or_merge(record)

    output = deduper.get_results()
    output.sort(
        key=lambda record: (
            bool(record.get("_location_verified")),
            bool(KEYWORD_RE.search(str(record.get("company_name", "")))),
            bool(record.get("website")),
            bool(record.get("phone")),
            bool(record.get("email")),
        ),
        reverse=True,
    )
    return output[:limit]


def discover_businesses_with_stats(
    city: str,
    limit: int = 25,
    category: str = "Digital Marketing",
    state: str = "",
) -> DiscoveryResult:
    """Run all enabled discovery sources, deduplicate candidates, and return diagnostics."""
    city = city.strip()
    state = state.strip()

    if not city:
        raise ValueError("City name cannot be empty.")
    if limit <= 0:
        return DiscoveryResult()

    all_records: list[dict[str, Any]] = []
    source_stats: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    # 1. OpenStreetMap Overpass
    osm_records, osm_raw, osm_error, osm_duration = _discover_openstreetmap(
        city, state, category, limit
    )
    all_records.extend(osm_records)
    source_stats["OpenStreetMap"] = {
        "raw": osm_raw,
        "unique": len(osm_records),
        "status": "error" if osm_error else "ok",
        "duration_seconds": osm_duration,
    }
    if osm_error:
        notes.append(osm_error)

    # 2. Overture Maps
    (
        overture_records,
        overture_raw,
        overture_error,
        overture_note,
        overture_duration,
    ) = _discover_overture(city, state, category, limit)
    all_records.extend(overture_records)
    source_stats["Overture Maps"] = {
        "raw": overture_raw,
        "unique": len(overture_records),
        "status": (
            "error"
            if overture_error
            else "disabled"
            if not OVERTURE_ENABLED
            else "ok"
        ),
        "duration_seconds": overture_duration,
    }
    if overture_error:
        notes.append(overture_error)
    if overture_note:
        notes.append(overture_note)

    # 3. SearXNG
    (
        searx_records,
        searx_raw,
        searx_error,
        searx_note,
        searx_duration,
    ) = _discover_searxng(city, state, category, limit)
    all_records.extend(searx_records)
    source_stats["SearXNG Web Search"] = {
        "raw": searx_raw,
        "unique": len(searx_records),
        "status": "error" if searx_error else "ok",
        "duration_seconds": searx_duration,
    }
    if searx_error:
        notes.append(searx_error)
    if searx_note:
        notes.append(searx_note)

    # 4. Wikidata
    (
        wikidata_records,
        wikidata_raw,
        wikidata_error,
        wikidata_note,
        wikidata_duration,
    ) = _discover_wikidata(city, state, category, limit)
    all_records.extend(wikidata_records)
    source_stats["Wikidata"] = {
        "raw": wikidata_raw,
        "unique": len(wikidata_records),
        "status": (
            "error"
            if wikidata_error
            else "ok"
            if WIKIDATA_ENABLED
            else "disabled"
        ),
        "duration_seconds": wikidata_duration,
    }
    if wikidata_error:
        notes.append(wikidata_error)
    if wikidata_note:
        notes.append(wikidata_note)

    # 5. India MCA Company Master Data
    (
        mca_records,
        mca_raw,
        mca_error,
        mca_note,
        mca_duration,
    ) = _discover_mca_registry(city, state, category, limit)
    all_records.extend(mca_records)
    source_stats["India MCA Company Master Data"] = {
        "raw": mca_raw,
        "unique": len(mca_records),
        "status": (
            "error"
            if mca_error
            else "ok"
            if MCA_ENABLED
            else "disabled"
        ),
        "duration_seconds": mca_duration,
    }
    if mca_error:
        notes.append(mca_error)
    if mca_note:
        notes.append(mca_note)

    # 6. AllThePlaces
    (
        atp_records,
        atp_raw,
        atp_error,
        atp_note,
        atp_duration,
    ) = _discover_alltheplaces(city, state, category, limit)
    all_records.extend(atp_records)
    source_stats["AllThePlaces"] = {
        "raw": atp_raw,
        "unique": len(atp_records),
        "status": (
            "error"
            if atp_error
            else "ok"
            if atp_records
            else "no_data"
            if ALLTHEPLACES_ENABLED
            else "disabled"
        ),
        "duration_seconds": atp_duration,
    }
    if atp_error:
        notes.append(atp_error)
    if atp_note:
        notes.append(atp_note)

    # Merge candidates across sources using indexed deduplication
    businesses = _merge_sources(all_records, limit)

    # 7. Common Crawl candidate corroboration (targeted on merged candidates)
    cc_checked, cc_matched, cc_note = corroborate_with_common_crawl(businesses)
    source_stats["Common Crawl"] = {
        "raw": cc_checked,
        "unique": cc_matched,
        "status": "ok" if COMMONCRAWL_ENABLED else "disabled",
    }
    if cc_note:
        notes.append(cc_note)

    for record in businesses:
        record.setdefault("sector", category or "Digital Marketing")

    print(
        f"[discovery] Source unique counts for {city}: "
        f"OSM={len(osm_records)}, "
        f"Overture={len(overture_records)}, "
        f"SearXNG={len(searx_records)}, "
        f"Wikidata={len(wikidata_records)}, "
        f"MCA={len(mca_records)}, "
        f"AllThePlaces={len(atp_records)}, "
        f"CommonCrawlCorroborated={cc_matched}; "
        f"combined unique={len(businesses)}."
    )

    return DiscoveryResult(
        businesses=businesses,
        source_stats=source_stats,
        notes=notes,
    )


def discover_businesses(
    city: str,
    limit: int = 25,
    category: str = "Digital Marketing",
    state: str = "",
) -> list[dict[str, Any]]:
    """Backward-compatible list-returning function."""
    return discover_businesses_with_stats(
        city=city,
        limit=limit,
        category=category,
        state=state,
    ).businesses
