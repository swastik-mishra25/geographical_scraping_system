"""Multi-source business discovery for the geographical lead POC.

Sources:
- OpenStreetMap Overpass (open geographic/business data)
- Overture Maps Places (open dataset; optional DuckDB dependency)
- SearXNG (local/self-hosted metasearch endpoint; results depend on enabled engines)

This module discovers candidates only. Website enrichment, contact validation,
deduplication in the main pipeline, and ICP/Dakini scoring remain downstream.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

import requests

from app.config import HEADERS, OVERPASS_URL

# Source configuration
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERTURE_STAC_URL = "https://stac.overturemaps.org/catalog.json"
OVERTURE_S3_PREFIX = "s3://overturemaps-us-west-2/release"

SEARXNG_URL = os.getenv(
    "SEARXNG_URL", "http://localhost:8080"
).rstrip("/")

SEARXNG_MAX_REQUESTS = max(
    1, int(os.getenv("SEARXNG_MAX_REQUESTS", "8"))
)

OVERTURE_ENABLED = (
    os.getenv("OVERTURE_ENABLED", "false")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

OVERTURE_MAX_ROWS = max(
    100, int(os.getenv("OVERTURE_MAX_ROWS", "1500"))
)

# Wikidata: public API, no API key required.
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"

WIKIDATA_ENABLED = (
    os.getenv("WIKIDATA_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

WIKIDATA_MAX_SEARCHES = max(
    1, min(2, int(os.getenv("WIKIDATA_MAX_SEARCHES", "1")))
)

# MCA is an optional local company-registry snapshot.
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

KEYWORD_REGEX = (
    r"digital marketing|marketing|advertising|advertisement|media|creative|"
    r"branding|seo|social media|performance marketing|search engine optimization|"
    r"content marketing|growth marketing|lead generation|marketing agency"
)

KEYWORD_RE = re.compile(KEYWORD_REGEX, re.IGNORECASE)

# Skip social networks and business directories when identifying official websites.
NON_COMPANY_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "pinterest.com",
    "wikipedia.org",
    "reddit.com",
    "justdial.com",
    "sulekha.com",
    "indiamart.com",
    "tradeindia.com",
    "clutch.co",
    "goodfirms.co",
    "sortlist.com",
    "ambitionbox.com",
    "glassdoor.com",
    "indeed.com",
    "naukri.com",
    "google.com",
    "maps.google.com",
    "bing.com",
    "yelp.com",
    "yellowpages.com",
    "crunchbase.com",
}

CITY_CACHE: dict[
    str, tuple[float, float, float, float, str]
] = {}

_NOMINATIM_LOCK = Lock()
_LAST_NOMINATIM_REQUEST = 0.0


@dataclass
class DiscoveryResult:
    businesses: list[dict[str, Any]] = field(default_factory=list)
    source_stats: dict[
        str, dict[str, int | str]
    ] = field(default_factory=dict)
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

    cache_key = (
        f"{clean_city.casefold()}|{clean_state.casefold()}"
    )

    if cache_key in CITY_CACHE:
        return CITY_CACHE[cache_key]

    query = ", ".join(
        part
        for part in (clean_city, clean_state, "India")
        if part
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
        if place.get("boundingbox")
        and place.get("lat")
        and place.get("lon")
    ]

    if not places:
        raise ValueError(
            f"Could not find geographic bounds for '{query}'."
        )

    def rank_place(
        place: dict[str, Any],
    ) -> tuple[int, float]:
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
            south, north, west, east = map(
                float, place["boundingbox"]
            )
            area = (north - south) * (east - west)
        except (KeyError, TypeError, ValueError):
            area = 0.0

        return priority, -area

    place = sorted(places, key=rank_place)[0]

    south, north, west, east = map(
        float, place["boundingbox"]
    )

    # If only a point-sized geometry was returned, use a modest radius.
    if (north - south) < 0.02 and (east - west) < 0.02:
        latitude = float(place["lat"])
        longitude = float(place["lon"])

        lat_padding = 0.15
        lon_padding = 0.15 / max(
            math.cos(math.radians(latitude)), 0.3
        )

        south = max(-90.0, latitude - lat_padding)
        north = min(90.0, latitude + lat_padding)
        west = max(-180.0, longitude - lon_padding)
        east = min(180.0, longitude + lon_padding)

    resolved_state = (
        place.get("address", {}).get("state", "")
        or clean_state
    )

    bounds = (
        south,
        west,
        north,
        east,
        resolved_state,
    )

    CITY_CACHE[cache_key] = bounds

    print(
        f"[discovery] Geocoded {query}: "
        f"bounds={(south, west, north, east)}"
    )

    return bounds


def _build_overpass_query(
    south: float,
    west: float,
    north: float,
    east: float,
) -> str:
    bbox = (
        f"({south:.6f},{west:.6f},"
        f"{north:.6f},{east:.6f})"
    )

    return f"""
    [out:json][timeout:60];
    (
      nwr{bbox}["office"~"^(advertising_agency|marketing|media|design)$"];
      nwr{bbox}["craft"~"^(advertising|graphic_designer)$"];
      nwr{bbox}["name"~"{KEYWORD_REGEX}",i];
    );
    out center tags;
    """


def _normalize_indian_mobile(value: Any) -> str:
    """Return unambiguous Indian mobile numbers in +91XXXXXXXXXX format."""
    if value is None:
        return ""

    digits = re.sub(r"\D", "", str(value).strip())

    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if (
        len(digits) == 12
        and digits.startswith("91")
        and digits[2] in "6789"
    ):
        return "+" + digits

    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits

    return ""


def _plain_value(value: Any) -> str:
    """Convert source values to text safely."""
    if value is None:
        return ""

    if isinstance(value, (str, int, float)):
        return str(value).strip()

    if isinstance(value, dict):
        for key in ("value", "url", "phone", "email", "name"):
            if value.get(key):
                return str(value[key]).strip()
        return ""

    if isinstance(value, (list, tuple)):
        for item in value:
            result = _plain_value(item)
            if result:
                return result
        return ""

    return str(value).strip()


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

        return (
            f"{parsed.scheme.lower()}://"
            f"{parsed.netloc.lower()}"
        )

    except ValueError:
        return ""


def _normalized_name(record: dict[str, Any]) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        str(record.get("company_name", "")).casefold(),
    )


def _normalized_domain(record: dict[str, Any]) -> str:
    website = _canonical_website(
        str(record.get("website", ""))
    )

    if not website:
        return ""

    return (
        urlsplit(website)
        .hostname
        .removeprefix("www.")
        .casefold()
    )


def _relevance_score(
    record: dict[str, Any],
    extra_text: str = "",
) -> int:
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

    score = (
        10
        if KEYWORD_RE.search(
            str(record.get("company_name", ""))
        )
        else 0
    )

    if KEYWORD_RE.search(text):
        score += 5

    if record.get("website"):
        score += 2

    if record.get("phone"):
        score += 1

    if record.get("email"):
        score += 1

    return score


def _merge_duplicate(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    """Keep useful fields when multiple sources identify the same business."""
    for field_name in (
        "website",
        "phone",
        "email",
        "city",
        "state",
        "address",
        "category",
    ):
        if not current.get(field_name) and incoming.get(field_name):
            current[field_name] = incoming[field_name]

    sources = set(
        str(current.get("source", "")).split("; ")
    )

    sources.update(
        str(incoming.get("source", "")).split("; ")
    )

    current["source"] = "; ".join(
        sorted(source for source in sources if source)
    )

    current["_location_verified"] = bool(
        current.get("_location_verified")
        or incoming.get("_location_verified")
    )

    combined = " ".join(
        part
        for part in (
            str(current.get("_relevance_text", "")),
            str(incoming.get("_relevance_text", "")),
        )
        if part
    )

    current["_relevance_text"] = combined[:3000]


def _dedupe_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    for record in records:
        name = _normalized_name(record)
        domain = _normalized_domain(record)

        if not name:
            continue

        existing = next(
            (
                item
                for item in output
                if name == _normalized_name(item)
                or (
                    domain
                    and _normalized_domain(item)
                    and domain == _normalized_domain(item)
                )
            ),
            None,
        )

        if existing is None:
            output.append(record)
        else:
            _merge_duplicate(existing, record)

    return output


def _discover_openstreetmap(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None]:
    """Discover geographic business records through OpenStreetMap."""
    try:
        (
            south,
            west,
            north,
            east,
            geocoded_state,
        ) = get_city_bounds(city, state)

        query = _build_overpass_query(
            south, west, north, east
        )

        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=HEADERS,
            timeout=90,
        )

        if not response.ok:
            raise RuntimeError(
                f"Overpass returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        data = response.json()
        elements = data.get("elements", [])

        if data.get("remark") and not elements:
            raise RuntimeError(
                f"Overpass query failed: {data['remark']}"
            )

        print(
            f"[discovery] Overpass returned "
            f"{len(elements)} raw elements for {city}."
        )

        records: list[dict[str, Any]] = []

        for element in elements:
            tags = element.get("tags", {}) or {}
            name = str(tags.get("name") or "").strip()

            if not name:
                continue

            website = _canonical_website(
                tags.get("website")
                or tags.get("contact:website")
                or ""
            )

            phone = _normalize_indian_mobile(
                tags.get("phone")
                or tags.get("contact:phone")
                or ""
            )

            email = str(
                tags.get("email")
                or tags.get("contact:email")
                or ""
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
                    or ""
                ),
                "city": str(
                    tags.get("addr:city") or city
                ).strip(),
                "state": str(
                    tags.get("addr:state")
                    or geocoded_state
                    or state
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

        records = _dedupe_records(records)

        records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )

        for record in records:
            record.pop("_discovery_relevance", None)

        return records[:limit], len(elements), None

    except Exception as exc:
        message = f"OpenStreetMap discovery failed: {exc}"
        print(f"[discovery] {message}")
        return [], 0, message


def _get_overture_release() -> str:
    response = requests.get(
        OVERTURE_STAC_URL,
        headers=HEADERS,
        timeout=25,
    )

    response.raise_for_status()

    release = str(
        response.json().get("latest", "")
    ).strip()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise RuntimeError(
            "Overture STAC catalog did not return "
            "a recognized latest release."
        )

    return release


def _discover_overture(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str]:
    """Query Overture Places via DuckDB when enabled and installed."""
    if not OVERTURE_ENABLED:
        return (
            [],
            0,
            None,
            "Overture Maps disabled by OVERTURE_ENABLED.",
        )

    try:
        import duckdb
    except ImportError:
        return (
            [],
            0,
            None,
            "Overture Maps skipped: install DuckDB with "
            "`pip install duckdb` to enable it.",
        )

    try:
        (
            south,
            west,
            north,
            east,
            geocoded_state,
        ) = get_city_bounds(city, state)

        release = _get_overture_release()

        parquet_path = (
            f"{OVERTURE_S3_PREFIX}/{release}/"
            "theme=places/type=place/*"
        )

        connection = duckdb.connect(database=":memory:")

        try:
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")
            connection.execute("INSTALL spatial")
            connection.execute("LOAD spatial")
            connection.execute("SET s3_region='us-west-2'")

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

            name = _plain_value(name)

            if not name:
                continue

            record = {
                "company_name": name,
                "sector": category or "Digital Marketing",
                "category": (
                    _plain_value(taxonomy)
                    or _plain_value(basic_category)
                ),
                "city": _plain_value(locality) or city,
                "state": (
                    _plain_value(region)
                    or geocoded_state
                    or state
                ),
                "address": _plain_value(address),
                "website": _canonical_website(
                    _plain_value(website)
                ),
                "phone": _normalize_indian_mobile(
                    _plain_value(phone)
                ),
                "email": _plain_value(email),
                "source": "Overture Maps",
                "_location_verified": True,
                "_relevance_text": (
                    f"{_plain_value(taxonomy)} "
                    f"{_plain_value(basic_category)} "
                    f"confidence={confidence}"
                ),
            }

            record["_discovery_relevance"] = _relevance_score(record)
            records.append(record)

        records = _dedupe_records(records)

        records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )

        for record in records:
            record.pop("_discovery_relevance", None)

        print(
            f"[discovery] Overture Maps returned {len(rows)} "
            f"matching raw rows for {city} ({release})."
        )

        return (
            records[:limit],
            len(rows),
            None,
            f"Overture Maps release used: {release}.",
        )

    except Exception as exc:
        message = f"Overture Maps discovery failed: {exc}"
        print(f"[discovery] {message}")

        return (
            [],
            0,
            message,
            "Overture Maps was attempted but failed; see discovery logs.",
        )


def _searxng_queries(
    city: str,
    state: str,
    category: str,
) -> list[str]:
    place = ", ".join(
        part
        for part in (city.strip(), state.strip(), "India")
        if part
    )

    requested_category = (
        category or "Digital Marketing"
    ).strip()

    return list(dict.fromkeys([
        f'"{requested_category}" agency in {place}',
        f"digital marketing agency in {place}",
        f"SEO and performance marketing companies in {place}",
        f"social media marketing and branding agency in {place}",
        f"advertising and creative agency in {place}",
        f"lead generation agency in {place}",
    ]))


def _is_blocked_domain(domain: str) -> bool:
    domain = domain.casefold().removeprefix("www.")

    return any(
        domain == blocked or domain.endswith("." + blocked)
        for blocked in NON_COMPANY_DOMAINS
    )


def _name_from_search_title(title: str) -> str:
    title = re.sub(
        r"\s*[|–—]\s*(official website|home|homepage|digital marketing agency|seo agency)\s*$",
        "",
        title,
        flags=re.I,
    )

    title = re.split(
        r"\s+[|–—]\s+",
        title,
        maxsplit=1,
    )[0]

    return title.strip(" \t\r\n-|–—:")[:180]


def _discover_searxng(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str]:
    """Discover candidates using the local SearXNG JSON API."""
    raw_count = 0
    records: list[dict[str, Any]] = []
    queries = _searxng_queries(city, state, category)
    requests_used = 0
    last_error: str | None = None

    for query in queries:
        for page in (1, 2):
            if (
                requests_used >= SEARXNG_MAX_REQUESTS
                or len(_dedupe_records(records)) >= limit
            ):
                break

            try:
                response = requests.get(
                    f"{SEARXNG_URL}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "language": "en",
                        "pageno": page,
                        "safesearch": 1,
                    },
                    headers=HEADERS,
                    timeout=35,
                )

                requests_used += 1

                if not response.ok:
                    raise RuntimeError(
                        f"SearXNG returned HTTP {response.status_code}: "
                        f"{response.text[:180]}"
                    )

                data = response.json()
                results = data.get("results", []) or []
                raw_count += len(results)

                print(
                    f"[discovery] SearXNG returned {len(results)} "
                    f"results for {query!r} (page={page})."
                )

                for item in results:
                    title = str(item.get("title") or "").strip()
                    url = str(item.get("url") or "").strip()
                    snippet = str(
                        item.get("content")
                        or item.get("snippet")
                        or ""
                    ).strip()

                    website = _canonical_website(url)

                    if not title or not website:
                        continue

                    domain = _normalized_domain({
                        "website": website
                    })

                    if not domain or _is_blocked_domain(domain):
                        continue

                    name = _name_from_search_title(title)

                    if not name or len(name) < 2:
                        continue

                    evidence = " ".join((title, snippet, url))
                    local_text = evidence.casefold()

                    location_verified = bool(
                        (city and city.casefold() in local_text)
                        or (state and state.casefold() in local_text)
                    )

                    record = {
                        "company_name": name,
                        "sector": category or "Digital Marketing",
                        "category": (
                            "Digital Marketing / Agency "
                            "(web result; verify during enrichment)"
                        ),
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

                    record["_discovery_relevance"] = (
                        _relevance_score(record, evidence)
                    )

                    records.append(record)

            except Exception as exc:
                last_error = f"SearXNG discovery failed: {exc}"
                print(f"[discovery] {last_error}")
                break

        if last_error:
            break

        if (
            requests_used >= SEARXNG_MAX_REQUESTS
            or len(_dedupe_records(records)) >= limit
        ):
            break

    records = _dedupe_records(records)

    records.sort(
        key=lambda item: (
            item.get("_location_verified", False),
            item.get("_discovery_relevance", 0),
        ),
        reverse=True,
    )

    for record in records:
        record.pop("_discovery_relevance", None)

    note = last_error or (
        f"SearXNG used {requests_used} request(s); "
        f"cap is {SEARXNG_MAX_REQUESTS}."
    )

    return records[:limit], raw_count, last_error, note


def _wikidata_claim_value(
    entity: dict[str, Any],
    property_id: str,
) -> Any:
    """Return the first usable Wikidata claim value."""
    claims = entity.get("claims", {}) or {}

    for claim in claims.get(property_id, []) or []:
        value = (
            (claim.get("mainsnak") or {})
            .get("datavalue", {})
            .get("value")
        )

        if value is not None:
            return value

    return None


def _wikidata_location_ids(
    entity: dict[str, Any],
) -> list[str]:
    ids: list[str] = []

    for property_id in ("P159", "P131"):
        value = _wikidata_claim_value(entity, property_id)

        if isinstance(value, dict) and value.get("id"):
            ids.append(str(value["id"]))

    return list(dict.fromkeys(ids))


def _discover_wikidata(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str]:
    """Discover company candidates through Wikidata's public API."""
    if not WIKIDATA_ENABLED:
        return (
            [],
            0,
            None,
            "Wikidata disabled by WIKIDATA_ENABLED.",
        )

    search_terms = list(dict.fromkeys([
        f"digital marketing agency {city} {state} India".strip(),
        f"advertising agency {city} {state} India".strip(),
        f"marketing company {city} {state} India".strip(),
    ]))[:WIKIDATA_MAX_SEARCHES]

    search_items: dict[str, dict[str, Any]] = {}
    raw_count = 0

    try:
        for query in search_terms:
            response = requests.get(
                WIKIDATA_API_URL,
                params={
                    "action": "wbsearchentities",
                    "search": query,
                    "language": "en",
                    "uselang": "en",
                    "type": "item",
                    "limit": min(20, max(10, limit)),
                    "format": "json",
                },
                headers={
                    **HEADERS,
                    "Accept": "application/json",
                },
                timeout=10,
            )

            response.raise_for_status()

            items = response.json().get("search", []) or []
            raw_count += len(items)

            for item in items:
                entity_id = str(item.get("id", "")).strip()

                if entity_id:
                    search_items.setdefault(entity_id, item)

            print(
                f"[discovery] Wikidata search returned {len(items)} "
                f"items for {query!r}."
            )

        if not search_items:
            return (
                [],
                raw_count,
                None,
                "Wikidata returned no candidate entities for this query.",
            )

        entity_ids = list(search_items)[:50]

        response = requests.get(
            WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(entity_ids),
                "props": "labels|descriptions|claims",
                "languages": "en",
                "format": "json",
            },
            headers={
                **HEADERS,
                "Accept": "application/json",
            },
            timeout=14,
        )

        response.raise_for_status()

        entities = response.json().get("entities", {}) or {}

        location_ids: set[str] = set()

        for entity in entities.values():
            location_ids.update(
                _wikidata_location_ids(entity)
            )

        location_labels: dict[str, str] = {}

        if location_ids:
            response = requests.get(
                WIKIDATA_API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(sorted(location_ids)[:50]),
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                },
                headers={
                    **HEADERS,
                    "Accept": "application/json",
                },
                timeout=10,
            )

            response.raise_for_status()

            location_entities = (
                response.json().get("entities", {}) or {}
            )

            for entity_id, entity in location_entities.items():
                label = (
                    (entity.get("labels", {}) or {})
                    .get("en", {})
                    .get("value", "")
                )

                if label:
                    location_labels[entity_id] = str(label)

        records: list[dict[str, Any]] = []

        for entity_id, entity in entities.items():
            label = str(
                (entity.get("labels", {}) or {})
                .get("en", {})
                .get("value", "")
            ).strip()

            description = str(
                (entity.get("descriptions", {}) or {})
                .get("en", {})
                .get("value", "")
            ).strip()

            if not label:
                continue

            evidence = f"{label} {description}"

            if not KEYWORD_RE.search(evidence):
                continue

            loc_labels = [
                location_labels.get(location_id, "")
                for location_id in _wikidata_location_ids(entity)
            ]

            location_text = " ".join(
                [description, *loc_labels]
            ).casefold()

            city_verified = bool(
                city and city.casefold() in location_text
            )

            # Do not assume a company is local when no evidence supports it.
            if not city_verified:
                continue

            website_claim = _wikidata_claim_value(entity, "P856")
            website = _canonical_website(
                str(website_claim or "")
            )

            record = {
                "company_name": label,
                "sector": category or "Digital Marketing",
                "category": (
                    description
                    or category
                    or "Digital Marketing"
                ),
                "city": city,
                "state": state,
                "address": ", ".join(
                    location for location in loc_labels if location
                ),
                "website": website,
                "phone": "",
                "email": "",
                "source": "Wikidata",
                "_location_verified": True,
                "_relevance_text": description,
            }

            record["_discovery_relevance"] = (
                _relevance_score(record, evidence)
            )

            records.append(record)

        records = _dedupe_records(records)

        records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )

        for record in records:
            record.pop("_discovery_relevance", None)

        return (
            records[:limit],
            raw_count,
            None,
            f"Wikidata searched {len(search_terms)} query phrase(s).",
        )

    except Exception as exc:
        message = f"Wikidata discovery failed: {exc}"
        print(f"[discovery] {message}")

        return (
            [],
            raw_count,
            message,
            "Wikidata was attempted but failed; see discovery logs.",
        )


def _iter_mca_rows(dataset_path: str):
    """Stream CSV rows from a CSV file or a ZIP containing a CSV."""
    path = Path(dataset_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"MCA dataset file not found: {path}"
        )

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".csv")
            ]

            if not members:
                raise ValueError(
                    "MCA ZIP file contains no CSV file. "
                    "Extract or convert the downloaded table to CSV."
                )

            # Prefer the largest CSV in the ZIP.
            member = max(
                members,
                key=lambda name: archive.getinfo(name).file_size,
            )

            with archive.open(member) as raw:
                with io.TextIOWrapper(
                    raw,
                    encoding="utf-8-sig",
                    errors="replace",
                    newline="",
                ) as stream:
                    yield from csv.DictReader(stream)

    else:
        with path.open(
            "r",
            encoding="utf-8-sig",
            errors="replace",
            newline="",
        ) as stream:
            yield from csv.DictReader(stream)


def _mca_field_map(
    row: dict[str, Any],
) -> dict[str, str]:
    return {
        re.sub(r"[^a-z0-9]", "", str(key).casefold()):
            str(value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _mca_pick(
    fields: dict[str, str],
    *names: str,
) -> str:
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.casefold())
        value = fields.get(key, "")

        if value:
            return value

    return ""


def _discover_mca_registry(
    city: str,
    state: str,
    category: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, str | None, str]:
    """Use an optional local MCA registry snapshot to find company matches.

    This is a company registry source, not a verified contact directory.
    """
    if not MCA_ENABLED:
        return (
            [],
            0,
            None,
            "MCA registry disabled by MCA_ENABLED.",
        )

    path = Path(MCA_DATASET_PATH)

    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        records: list[dict[str, Any]] = []
        raw_count = 0

        for row in _iter_mca_rows(str(path)):
            raw_count += 1
            fields = _mca_field_map(row)

            name = _mca_pick(
                fields,
                "company name",
                "companyname",
                "name of company",
            )

            if not name:
                continue

            status = _mca_pick(
                fields,
                "company status",
                "companystatus",
                "status",
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
                fields,
                "registered city",
                "city",
                "district",
            )

            state_field = _mca_pick(
                fields,
                "registered state",
                "registeredstate",
                "state",
            )

            location_text = (
                f"{city_field} {address}"
            ).casefold()

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

            # General company records are not automatically digital marketing leads.
            if not KEYWORD_RE.search(evidence):
                continue

            registration_date = _mca_pick(
                fields,
                "date of registration",
                "dateofregistration",
                "registration date",
                "incorporation date",
            )

            year_match = re.search(
                r"(?:19|20)\d{2}",
                registration_date,
            )

            company_age = (
                max(
                    0,
                    datetime.now().year
                    - int(year_match.group(0)),
                )
                if year_match
                else ""
            )

            record = {
                "company_name": name,
                "sector": category or "Digital Marketing",
                "category": (
                    activity
                    or "Company registry match; sector requires verification"
                ),
                "city": city_field or city,
                "state": state_field or state,
                "address": address,
                "website": "",
                "phone": "",
                "email": "",
                "source": "India MCA Company Master Data",
                "company_status": status,
                "company_age_years": company_age,
                "registration_date": registration_date,
                "cin": _mca_pick(
                    fields,
                    "corporate identification number",
                    "cin",
                    "corporateidentificationnumber",
                ),
                "_location_verified": True,
                "_relevance_text": activity,
            }

            record["_discovery_relevance"] = (
                _relevance_score(record, evidence)
            )

            records.append(record)

            if len(records) >= limit * 3:
                break

        records = _dedupe_records(records)

        records.sort(
            key=lambda item: item.get("_discovery_relevance", 0),
            reverse=True,
        )

        for record in records:
            record.pop("_discovery_relevance", None)

        print(
            f"[discovery] MCA registry scanned {raw_count} rows "
            f"and found {len(records)} local keyword matches for {city}."
        )

        return (
            records[:limit],
            raw_count,
            None,
            f"MCA company master snapshot: {path.name}.",
        )

    except Exception as exc:
        message = f"MCA registry discovery failed: {exc}"
        print(f"[discovery] {message}")

        return (
            [],
            0,
            message,
            "MCA registry was attempted but failed; see discovery logs.",
        )


def _merge_sources(
    records: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge source results, deduplicate and prioritize useful records."""
    output = _dedupe_records([
        dict(record) for record in records
    ])

    output.sort(
        key=lambda record: (
            bool(record.get("_location_verified")),
            bool(
                KEYWORD_RE.search(
                    str(record.get("company_name", ""))
                )
            ),
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
    """Run enabled sources, deduplicate candidates, and return diagnostics."""
    city = city.strip()
    state = state.strip()

    if not city:
        raise ValueError("City name cannot be empty.")

    if limit <= 0:
        return DiscoveryResult()

    all_records: list[dict[str, Any]] = []
    source_stats: dict[
        str, dict[str, int | str]
    ] = {}
    notes: list[str] = []

    # 1. OpenStreetMap
    osm_records, osm_raw, osm_error = (
        _discover_openstreetmap(
            city, state, category, limit
        )
    )

    all_records.extend(osm_records)

    source_stats["OpenStreetMap"] = {
        "raw": osm_raw,
        "unique": len(osm_records),
        "status": "error" if osm_error else "ok",
    }

    if osm_error:
        notes.append(osm_error)

    # 2. Overture Maps
    (
        overture_records,
        overture_raw,
        overture_error,
        overture_note,
    ) = _discover_overture(
        city, state, category, limit
    )

    all_records.extend(overture_records)

    source_stats["Overture Maps"] = {
        "raw": overture_raw,
        "unique": len(overture_records),
        "status": (
            "error"
            if overture_error
            else "disabled"
            if not OVERTURE_ENABLED
            else "skipped"
            if "skipped" in overture_note.lower()
            else "ok"
        ),
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
    ) = _discover_searxng(
        city, state, category, limit
    )

    all_records.extend(searx_records)

    source_stats["SearXNG Web Search"] = {
        "raw": searx_raw,
        "unique": len(searx_records),
        "status": "error" if searx_error else "ok",
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
    ) = _discover_wikidata(
        city, state, category, limit
    )

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
    ) = _discover_mca_registry(
        city, state, category, limit
    )

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
    }

    if mca_error:
        notes.append(mca_error)

    if mca_note:
        notes.append(mca_note)

    businesses = _merge_sources(
        all_records,
        limit,
    )

    for record in businesses:
        record.setdefault(
            "sector",
            category or "Digital Marketing",
        )

    print(
        f"[discovery] Source unique counts for {city}: "
        f"OSM={len(osm_records)}, "
        f"Overture={len(overture_records)}, "
        f"SearXNG={len(searx_records)}, "
        f"Wikidata={len(wikidata_records)}, "
        f"MCA={len(mca_records)}; "
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