"""Intelligent query and keyword generator for autonomous public-web discovery."""
from __future__ import annotations

from typing import Any
from app.config import get_industry_config, DISCOVERY_MAX_QUERIES


CITY_LOCALITIES_MAP: dict[str, list[str]] = {
    "mumbai": ["Andheri", "Bandra", "BKC", "Lower Parel", "Powai", "Thane", "Navi Mumbai", "Goregaon", "Malad", "Dadar", "Worli", "Fort", "Juhu", "Borivali"],
    "bengaluru": ["Koramangala", "Indiranagar", "HSR Layout", "Whitefield", "Electronic City", "Jayanagar", "Marathahalli", "BTM Layout", "Malleshwaram", "Bellandur"],
    "delhi": ["Connaught Place", "Nehru Place", "Saket", "Okhla", "South Extension", "Pitampura", "Janakpuri", "Dwarka", "Gurgaon", "Noida"],
    "pune": ["Kothrud", "Hinjewadi", "Viman Nagar", "Baner", "Wakad", "Koregaon Park", "Shivajinagar", "Aundh", "Magarpatta", "Hadapsar"],
    "hyderabad": ["Hitec City", "Madhapur", "Gachibowli", "Banjara Hills", "Jubilee Hills", "Kondapur", "Begumpet", "Secunderabad"],
    "bhubaneswar": ["Saheed Nagar", "Patia", "Nayapalli", "Infocity", "Chandrasekharpur", "Rasulgarh", "Khandagiri", "Jaydev Vihar"],
    "kolkata": ["Salt Lake Sector V", "Park Street", "New Town", "Bidhannagar", "Rajarhat", "Ballygunge", "Alipore", "Dalhousie"],
    "chennai": ["T Nagar", "OMR", "Guindy", "Anna Nagar", "Velachery", "Nungambakkam", "Adyar", "Mylapore"],
    "ahmedabad": ["SG Highway", "Prahlad Nagar", "Navrangpura", "Bodakdev", "Satellite", "Vastrapur", "Ashram Road"],
    "jaipur": ["Malviya Nagar", "Vaishali Nagar", "Mansarovar", "C Scheme", "MI Road", "Raja Park", "Tonk Road"],
}


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

    # 2. Locality-specific query matrix when locality is provided (e.g. Campaign Shards)
    if clean_locality and clean_locality.lower() != clean_city.lower():
        _add_query(f'{cfg["name"]} agency in {clean_locality} {clean_city}', "locality_core", 100)
        _add_query(f'{cfg["name"]} company {clean_locality} {clean_city}', "locality_company", 98)
        _add_query(f'SEO agency in {clean_locality} {clean_city}', "locality_seo", 96)
        _add_query(f'social media marketing agency {clean_locality} {clean_city}', "locality_smm", 94)
        _add_query(f'branding and creative agency {clean_locality} {clean_city}', "locality_branding", 92)
        _add_query(f'performance marketing agency {clean_locality} {clean_city}', "locality_perf", 90)
        for kw in keywords[:4]:
            _add_query(f'{kw} {clean_locality} {clean_city}', "locality_keyword", 88)
        _add_query(f'"{cfg["name"]}" agency in {loc_part}', "exact_core", 80)
        _add_query(f'{cfg["name"]} company in {clean_city}', "core_city", 78)
    else:
        _add_query(f'"{cfg["name"]}" agency in {loc_part}', "exact_core", 100)
        _add_query(f'{cfg["name"]} company in {clean_city}', "core_city", 95)
        city_lower = clean_city.lower()
        sub_locs = CITY_LOCALITIES_MAP.get(city_lower, [])
        for loc in sub_locs:
            _add_query(f'{cfg["name"]} agency {loc} {clean_city}', "regional_locality", 88)
            _add_query(f'SEO company {loc} {clean_city}', "regional_locality_seo", 84)

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

