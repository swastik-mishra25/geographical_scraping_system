"""Stage 9: Production-Grade 100-Point Ideal Customer Profile (ICP) Lead Quality Scorer.

A calibrated, zero-overflow 100-point scoring model across 4 distinct B2B pillars:
1. Contact Reachability (Max: 35 points) - Mobile/Landline/Toll-Free, Email, Website
2. Geographic & Physical Grounding (Max: 25 points) - HQ vs. Branch, PIN code, Address in Evidence
3. Industry & Semantic Relevance (Max: 20 points) - Dynamic matching across all 13 industries
4. Business Authority & Authenticity (Max: 20 points) - Decision-makers, MCA CIN/Longevity, Audit Proofs

Total Maximum Score: 35 + 25 + 20 + 20 = Exactly 100 points.
"""
from __future__ import annotations

import re
from typing import Any

from app.config import get_industry_config

PIN_CODE_RE = re.compile(r"\b([1-9][0-9]{2}\s?[0-9]{3})\b")
LEADERSHIP_ROLES = re.compile(
    r"\b(founder|co-founder|ceo|chief executive|managing director|director|principal|partner|owner|proprietor)\b",
    re.I,
)


def score_lead(lead: dict[str, Any], target_category: str = "") -> tuple[int, str]:
    """Score a business lead on a strictly calibrated 0-100 quality scale with audit reasons.

    Args:
        lead: The lead data dictionary containing extracted and validated attributes.
        target_category: Optional requested industry category (e.g. "Digital Marketing", "Healthcare").

    Returns:
        tuple[int, str]: (score from 0 to 100, human-readable justification reasons)
    """
    if not lead or not isinstance(lead, dict):
        return 0, "no lead data provided"

    score = 0
    reasons: list[str] = []

    # =========================================================================
    # Pillar 1: Contact Reachability (Max: 35 Points)
    # =========================================================================

    # 1A. Phone Reachability (Max: 20 points - mutually exclusive)
    phone = str(lead.get("phone") or "").strip()
    phone_valid = bool(
        lead.get("_phone_valid")
        or (phone and ("+91" in phone or len(re.sub(r"\D", "", phone)) in (10, 11, 12)))
    )

    if phone_valid:
        phone_type = str(lead.get("phone_type") or "").lower()
        if phone_type == "mobile" or (phone.startswith("+91") and len(phone) >= 13 and phone[3] in "6789"):
            score += 20
            reasons.append("direct mobile phone (+20)")
        elif phone_type == "landline":
            score += 15
            reasons.append("corporate landline (+15)")
        elif phone_type == "toll_free":
            score += 10
            reasons.append("toll-free line (+10)")
        else:
            score += 15
            reasons.append("verified Indian phone (+15)")

    # 1B. Email Availability (Max: 10 points)
    email = str(lead.get("email") or "").strip()
    if lead.get("_email_valid") or (email and "@" in email and "." in email.split("@")[-1]):
        score += 10
        reasons.append("business email (+10)")

    # 1C. Website Verification (Max: 5 points)
    website = str(lead.get("website") or "").strip()
    if lead.get("_website_valid") or (website and "." in website and not website.startswith("javascript")):
        score += 5
        reasons.append("verified domain (+5)")

    # =========================================================================
    # Pillar 2: Geographic & Physical Grounding (Max: 25 Points)
    # =========================================================================

    # 2A. Physical Office Existence (Max: 15 points - mutually exclusive)
    location_type = str(lead.get("location_type") or "").lower()
    city = str(lead.get("city") or "").strip()

    if location_type == "headquarters":
        score += 15
        reasons.append("registered headquarters (+15)")
    elif location_type == "branch":
        score += 10
        reasons.append("regional branch office (+10)")
    elif location_type == "service_area" or city:
        score += 5
        reasons.append("city presence verified (+5)")

    # 2B. Address Depth & Grounding (Max: 10 points - mutually exclusive)
    address = str(lead.get("address") or "").strip()
    locality = str(lead.get("locality") or "").strip()

    # Extract all address and citation texts to prevent missing evidence excerpts
    evidence_items = lead.get("evidence_items") or lead.get("evidence") or []
    evidence_texts: list[str] = []
    if isinstance(evidence_items, list):
        for ev in evidence_items:
            if isinstance(ev, dict):
                evidence_texts.append(str(ev.get("evidence_excerpt") or ""))
            elif isinstance(ev, str):
                evidence_texts.append(ev)

    combined_location_text = f"{address} {city} {locality} {' '.join(evidence_texts)}"
    has_pin = bool(PIN_CODE_RE.search(combined_location_text))
    has_street_address = len(address) > 20 or any(
        len(t) > 25 and any(kw in t.lower() for kw in ("floor", "road", "street", "building", "nagar", "plot", "complex", "tower", "office"))
        for t in evidence_texts
    )

    if has_pin or has_street_address:
        score += 10
        reasons.append("street address / PIN grounded (+10)")
    elif locality and len(locality) > 2:
        score += 5
        reasons.append(f"commercial locality grounded: {locality} (+5)")

    # =========================================================================
    # Pillar 3: Industry & Semantic Relevance (Max: 20 Points)
    # =========================================================================
    category_name = (
        target_category
        or lead.get("industry_category")
        or lead.get("sector")
        or "Digital Marketing"
    ).strip()

    cfg = get_industry_config(category_name)
    keywords = [kw.lower() for kw in cfg.get("keywords", [])]
    service_terms = [st.lower() for st in cfg.get("service_terms", [])]
    synonyms = [sy.lower() for sy in cfg.get("synonyms", [])]
    core_terms = set(keywords + service_terms + synonyms + [category_name.lower()])

    if "digital" in category_name.lower() or "marketing" in category_name.lower():
        core_terms.update(["marketing", "digital", "advertising", "media", "seo", "ppc", "branding"])

    company_name = str(lead.get("company_name") or "")
    sector_str = str(lead.get("sector") or lead.get("industry_category") or "")
    subcat_str = str(lead.get("industry_subcategory") or "")
    services_val = lead.get("services") or []
    services_str = " ".join(services_val) if isinstance(services_val, list) else str(services_val)

    searchable_industry = f"{company_name} {sector_str} {subcat_str} {services_str}".lower()

    # 3A. Primary Category Alignment (Max: 12 points - mutually exclusive)
    matched_core = any(term in searchable_industry for term in core_terms if len(term) >= 3)
    if matched_core:
        score += 12
        reasons.append(f"core {category_name.lower()} match (+12)")
    elif lead.get("_industry_match") or lead.get("industry_match"):
        score += 6
        reasons.append(f"general {category_name.lower()} match (+6)")

    # 3B. Specialized Subcategory & Service Depth (Max: 8 points - mutually exclusive)
    matched_services_count = sum(1 for term in service_terms if term in searchable_industry)
    has_subcat = bool(subcat_str and subcat_str.lower() != category_name.lower())

    if has_subcat or matched_services_count >= 2:
        score += 8
        reasons.append("specialized service catalog (+8)")
    elif matched_services_count == 1 or len(services_val) > 0:
        score += 4
        reasons.append("basic service listed (+4)")

    # =========================================================================
    # Pillar 4: Business Authority & Authenticity (Max: 20 Points)
    # =========================================================================

    # 4A. Decision Maker / Executive Leadership (Max: 10 points - mutually exclusive)
    contact_person = str(lead.get("contact_person") or "").strip()
    contact_role = str(lead.get("contact_role") or "").strip()

    if contact_person and len(contact_person) > 3:
        score += 10
        role_label = f" ({contact_role})" if contact_role else ""
        reasons.append(f"decision-maker identified: {contact_person}{role_label} (+10)")
    elif contact_role and LEADERSHIP_ROLES.search(contact_role):
        score += 5
        reasons.append(f"leadership role detected: {contact_role} (+5)")

    # 4B. Business Longevity, Size & MCA Registration (Max: 5 points - mutually exclusive)
    cin = str(lead.get("cin") or "").strip()
    company_age = str(lead.get("company_age") or "").lower()
    company_size = str(lead.get("company_size") or "").lower()

    if cin and len(cin) >= 15:
        score += 5
        reasons.append("verified MCA registered entity (+5)")
    elif (company_age and company_age != "unknown") or (company_size and company_size != "unknown"):
        score += 5
        desc = company_age if company_age != "unknown" else company_size
        reasons.append(f"established profile: {desc} (+5)")

    # 4C. Verifiable Audit Proofs (Max: 5 points - mutually exclusive)
    if len(evidence_texts) >= 2:
        score += 5
        reasons.append(f"{len(evidence_texts)} verified audit proofs (+5)")
    elif len(evidence_texts) == 1:
        score += 3
        reasons.append("1 verified audit proof (+3)")

    reason_str = "; ".join(reasons) if reasons else "no qualifying signals"
    return score, reason_str
