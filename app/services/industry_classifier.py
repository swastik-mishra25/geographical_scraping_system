"""Stage 6A: Industry Identification and Subcategory Classification."""
from __future__ import annotations

import re
from typing import Any
from app.config import get_industry_config

SUBCATEGORY_MATCHERS = {
    "SEO Agencies": [
        r"\bseo\b", r"search engine optimization", r"organic ranking", r"technical seo",
        r"link building", r"on-page seo", r"keyword research",
    ],
    "Performance Marketing": [
        r"performance marketing", r"roas", r"cost per acquisition", r"paid media",
        r"growth marketing", r"funnel optimization",
    ],
    "PPC Management": [
        r"\bppc\b", r"pay-per-click", r"google ads", r"search ads", r"adwords", r"meta ads",
    ],
    "Social Media Marketing": [
        r"social media marketing", r"\bsmm\b", r"instagram marketing", r"social media management",
        r"facebook ads", r"influencer marketing",
    ],
    "Content Marketing": [
        r"content marketing", r"copywriting", r"content creation", r"blog management",
        r"brand storytelling",
    ],
    "Branding and Creative Agencies": [
        r"branding agency", r"creative agency", r"brand identity", r"graphic design",
        r"logo design", r"brand strategy",
    ],
    "Marketing Automation": [
        r"marketing automation", r"crm marketing", r"email automation", r"hubspot", r"lead nurturing",
    ],
    "Lead Generation Agencies": [
        r"lead generation", r"b2b lead gen", r"sales pipeline", r"inbound leads",
    ],
    "Online Advertising": [
        r"online advertising", r"display advertising", r"programmatic ads", r"media buying",
    ],
}


def classify_industry(
    company_name: str,
    combined_text: str,
    page_titles: list[str],
    industry_category: str = "Digital Marketing",
) -> dict[str, Any]:
    """Identify if website represents a genuine business in the industry and determine subcategory."""
    cfg = get_industry_config(industry_category)
    searchable_text = f"{company_name} {' '.join(page_titles)} {combined_text}".lower()
    lower_text = combined_text.lower()
    lower_name = company_name.lower()
    all_titles = " ".join(page_titles).lower()

    # 1. Exclusion check (training institutes, job boards, personal portfolios)
    for excl in cfg.get("exclusion_terms", []):
        if re.search(r"\b" + re.escape(excl) + r"\b", searchable_text[:4000]):
            # If training institute or course terms appear prominently in homepage title/header, reject
            if excl in all_titles or ("course" in searchable_text[:1000] and "fees" in searchable_text[:1000]):
                return {
                    "is_match": False,
                    "rejection_reason": f"Identified as educational/training institute or directory ({excl})",
                    "industry_category": industry_category,
                    "subcategory": "",
                    "confidence": 0.0,
                    "evidence_excerpt": "",
                }

    # 2. Industry keyword evaluation
    matched_services: list[str] = []
    for term in cfg.get("service_terms", []):
        if re.search(r"\b" + re.escape(term) + r"\b", searchable_text):
            matched_services.append(term)

    matched_keywords: list[str] = []
    for kw in cfg.get("keywords", []):
        if re.search(r"\b" + re.escape(kw) + r"\b", searchable_text):
            matched_keywords.append(kw)

    total_matches = len(matched_services) + len(matched_keywords)
    has_core_marker = any(
        term in searchable_text
        for term in (
            "digital marketing",
            "seo",
            "search engine",
            "performance marketing",
            "advertising agency",
            "creative agency",
            "social media marketing",
            "ppc",
        )
    )

    if total_matches < 1 or not has_core_marker:
        return {
            "is_match": False,
            "rejection_reason": "Insufficient industry service evidence on website",
            "industry_category": industry_category,
            "subcategory": "",
            "confidence": 0.2,
            "evidence_excerpt": "",
        }

    # 3. Determine most specific subcategory
    best_subcategory = "Digital Marketing Agencies"
    highest_hits = 0

    for subcat_name, patterns in SUBCATEGORY_MATCHERS.items():
        hits = sum(1 for pat in patterns if re.search(pat, lower_text))
        if hits > highest_hits:
            highest_hits = hits
            best_subcategory = subcat_name

    # Extract supporting evidence snippet
    evidence_snippet = ""
    for sentence in re.split(r"[.\n]", combined_text):
        clean_sentence = sentence.strip()
        if 20 < len(clean_sentence) < 200:
            if any(term in clean_sentence.lower() for term in ("seo", "digital marketing", "social media", "performance marketing", "advertising")):
                evidence_snippet = clean_sentence
                break

    confidence = min(0.95, 0.5 + (0.05 * total_matches))

    return {
        "is_match": True,
        "industry_category": cfg["name"],
        "subcategory": best_subcategory,
        "services": matched_services[:8],
        "confidence": round(confidence, 2),
        "evidence_excerpt": evidence_snippet or f"Services identified: {', '.join(matched_services[:4])}",
    }
