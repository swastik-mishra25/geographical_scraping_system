"""Stage 6B: Geographical Location Verification and Evidence Assessment."""
from __future__ import annotations

import re
from typing import Any

# Regex to detect 6-digit Indian Postal PIN codes
PIN_CODE_RE = re.compile(r"\b([1-9][0-9]{2}\s?[0-9]{3})\b")

HQ_TERMS = re.compile(r"\b(head office|corporate office|registered office|headquarters|hq|main office)\b", re.I)
BRANCH_TERMS = re.compile(r"\b(branch office|regional office|our branches|our locations|locations)\b", re.I)
SERVICE_AREA_TERMS = re.compile(r"\b(serving|clients in|services in|service area)\b", re.I)


def verify_location(
    city: str,
    state: str,
    country: str,
    locality: str,
    crawled_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify company presence in the target city and determine location type (HQ, branch, service-area)."""
    clean_city = (city or "").strip().lower()
    clean_state = (state or "").strip().lower()
    clean_locality = (locality or "").strip().lower()

    if not clean_city:
        return {
            "verified": False,
            "location_type": "unverified",
            "evidence_excerpt": "No city specified for verification",
            "source_url": "",
            "locality": locality,
        }

    # Search contact pages first, then other pages
    sorted_pages = sorted(
        crawled_pages,
        key=lambda p: 0 if p.get("page_type") in ("contact", "about") else 1,
    )

    detected_type = "unverified"
    best_evidence = ""
    best_url = ""
    matched_locality = locality

    for page in sorted_pages:
        page_text = page.get("text", "")
        page_url = page.get("url", "")
        lower_page = page_text.lower()

        if clean_city not in lower_page:
            continue

        # Split into paragraphs or address blocks
        blocks = re.split(r"[\n\r]+", page_text)
        for block in blocks:
            b_clean = block.strip()
            b_lower = b_clean.lower()
            if clean_city in b_lower and len(b_clean) < 300:
                has_pin = bool(PIN_CODE_RE.search(b_clean))
                is_contact_page = page.get("page_type") == "contact"

                # Check for explicit Branch Office first
                if BRANCH_TERMS.search(b_lower):
                    detected_type = "branch"
                    best_evidence = b_clean
                    best_url = page_url
                    break
                # Check for explicit Headquarters / Corporate Office
                elif HQ_TERMS.search(b_lower) or (is_contact_page and has_pin):
                    detected_type = "headquarters"
                    best_evidence = b_clean
                    best_url = page_url
                    break
                # Service area indication
                elif SERVICE_AREA_TERMS.search(b_lower) and detected_type == "unverified":
                    detected_type = "service_area"
                    best_evidence = b_clean
                    best_url = page_url
                elif detected_type == "unverified" and not best_evidence:
                    best_evidence = b_clean
                    best_url = page_url
                    best_evidence = b_clean
                    best_url = page_url

        if detected_type in ("headquarters", "branch"):
            break

    # Check locality if provided
    if clean_locality and clean_locality in " ".join(p.get("text", "").lower() for p in crawled_pages):
        matched_locality = locality

    # If evidence found but no explicit HQ/Branch marker
    if best_evidence and detected_type == "unverified":
        if any(p.get("page_type") == "contact" for p in crawled_pages):
            detected_type = "branch"
        else:
            detected_type = "service_area"

    is_verified = detected_type in ("headquarters", "branch")

    return {
        "verified": is_verified,
        "location_type": detected_type,
        "evidence_excerpt": best_evidence[:250] or f"Located in {city}",
        "source_url": best_url or (crawled_pages[0]["url"] if crawled_pages else ""),
        "locality": matched_locality,
    }
