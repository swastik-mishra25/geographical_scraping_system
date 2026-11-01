"""Intelligent query and keyword generator for autonomous public-web discovery."""
from __future__ import annotations

from typing import Any
from app.config import get_industry_config, DISCOVERY_MAX_QUERIES


def generate_discovery_queries(
    industry: str,
    city: str,
    state: str = "",
    country: str = "India",
    locality: str = "",
    max_queries: int = DISCOVERY_MAX_QUERIES,
) -> list[dict[str, Any]]:
    """Generate prioritized discovery queries based on industry, subcategories, and location."""
    clean_city = (city or "").strip()
    clean_state = (state or "").strip()
    clean_country = (country or "India").strip()
    clean_locality = (locality or "").strip()

    cfg = get_industry_config(industry)
    subcategories = cfg.get("subcategories", [])
    keywords = cfg.get("keywords", [])
    synonyms = cfg.get("synonyms", [])

    queries_set: set[str] = set()
    prioritized_queries: list[dict[str, Any]] = []

    def _add_query(query_text: str, query_type: str, weight: int) -> None:
        q = " ".join(query_text.split()).strip()
        if q and q.lower() not in queries_set:
            queries_set.add(q.lower())
            prioritized_queries.append({
                "query": q,
                "type": query_type,
                "weight": weight,
                "industry": cfg.get("name", industry),
                "city": clean_city,
                "state": clean_state,
            })

    # 1. Primary core industry location query
    loc_part = f"{clean_city}"
    if clean_state:
        loc_part += f" {clean_state}"
    if clean_country and clean_country.lower() != "india":
        loc_part += f" {clean_country}"

    _add_query(f'"{cfg["name"]}" agency in {loc_part}', "exact_core", 100)
    _add_query(f'{cfg["name"]} company in {clean_city}', "core_city", 95)

    # 2. Locality-specific query if locality provided
    if clean_locality:
        _add_query(f'{cfg["name"]} in {clean_locality} {clean_city}', "locality_core", 90)
        _add_query(f'SEO agency in {clean_locality} {clean_city}', "locality_seo", 88)

    # 3. High-intent subcategory queries
    high_intent_subs = [
        "SEO Agencies",
        "Performance Marketing",
        "Social Media Marketing",
        "PPC Management",
        "Branding and Creative Agencies",
        "Lead Generation Agencies",
        "Growth Marketing",
    ]
    for sub in high_intent_subs:
        if sub in subcategories:
            sub_term = sub.rstrip("s") if sub.endswith("ies") or sub.endswith("s") else sub
            if sub.endswith("Agencies"):
                sub_term = sub[:-3] + "y"
            _add_query(f"{sub_term} in {clean_city}", "subcategory", 85)

    # 4. Keyword & synonym combinations
    for kw in keywords[:5]:
        _add_query(f"{kw} agency {clean_city}", "keyword", 75)

    for syn in synonyms[:3]:
        _add_query(f"{syn} in {clean_city}", "synonym", 70)

    # Sort queries by weight descending and limit to max_queries
    prioritized_queries.sort(key=lambda x: x["weight"], reverse=True)
    return prioritized_queries[:max_queries]

