"""Stage 7: Public business data extraction without fabrication."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup

from app.services.dedupe import normalize_name

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:(?:\+|0{0,2})91[\s.-]?)?(?:[6-9]\d{4}[\s.-]?\d{5}|[6-9]\d{9})\b")
FOUNDED_RE = re.compile(r"\b(?:founded|established|est\.?|since)\s+(?:in\s+)?(19\d{2}|20[0-2]\d)\b", re.I)
TEAM_SIZE_RE = re.compile(r"\b([1-9][0-9]{0,3}\+?\s*(?:employees|professionals|team members|specialists))\b", re.I)
LEADERSHIP_ROLES = re.compile(r"\b(founder|co-founder|ceo|managing director|director|principal)\b", re.I)

IGNORED_EMAIL_DOMAINS = {
    "example.com", "domain.com", "yourdomain.com", "sentry.io",
    "wixpress.com", "wordpress.org", "schema.org", "bootstrap.com",
}


def normalize_indian_phone(value: str) -> str:
    """Normalize valid Indian mobile or landline number to +91XXXXXXXXXX format."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return ""


def _extract_company_name(root_url: str, crawled_pages: list[dict[str, Any]]) -> str:
    """Extract official company name from metadata, logo, or title tags."""
    if not crawled_pages:
        dom = urlsplit(root_url).netloc.replace("www.", "").split(".")[0]
        return dom.capitalize()

    home_page = crawled_pages[0]
    soup: BeautifulSoup = home_page.get("soup")

    if soup:
        # 1. OpenGraph site name
        og_name = soup.find("meta", property="og:site_name")
        if og_name and og_name.get("content"):
            name = og_name["content"].strip()
            if len(name) < 50:
                return normalize_name(name)

        # 2. Schema.org Organization name
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") in ("Organization", "LocalBusiness"):
                    if data.get("name"):
                        return normalize_name(str(data["name"]))
            except Exception:
                pass

        # 3. Clean Title tag
        raw_title = home_page.get("title", "")
        if raw_title:
            # Common title formats: "Apex Digital | Best SEO Agency in Mumbai"
            clean_part = re.split(r"[-|:–—]", raw_title)[0].strip()
            if 2 < len(clean_part) < 60:
                return normalize_name(clean_part)

    dom = urlsplit(root_url).netloc.replace("www.", "").split(".")[0]
    return dom.replace("-", " ").capitalize()


def extract_business_data(
    root_url: str,
    crawled_pages: list[dict[str, Any]],
    industry_category: str = "Digital Marketing",
    city: str = "",
    state: str = "",
    country: str = "India",
    locality: str = "",
) -> dict[str, Any]:
    """Extract verifiable business information from crawled pages without fabrication."""
    now = datetime.now(timezone.utc).isoformat()
    evidence_items: list[dict[str, Any]] = []

    company_name = _extract_company_name(root_url, crawled_pages)
    evidence_items.append({
        "field_name": "company_name",
        "field_value": company_name,
        "source_url": root_url,
        "evidence_excerpt": f"Company identity established from {root_url}",
        "verification_status": "verified",
    })

    phone = ""
    email = ""
    contact_person = ""
    contact_role = ""
    company_size = "unknown"
    company_age = "unknown"

    all_text = " ".join(p.get("text", "") for p in crawled_pages)

    # 1. Inspect links and page content for contact information
    for page in crawled_pages:
        soup: BeautifulSoup = page.get("soup")
        p_url = page.get("url", root_url)
        if not soup:
            continue

        # Check tel: links (highest accuracy)
        if not phone:
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if href.lower().startswith("tel:"):
                    norm = normalize_indian_phone(unquote(href[4:]))
                    if norm:
                        phone = norm
                        evidence_items.append({
                            "field_name": "phone",
                            "field_value": phone,
                            "source_url": p_url,
                            "evidence_excerpt": f"Published tel link: {href}",
                            "verification_status": "verified",
                        })
                        break

        # Check mailto: links (highest accuracy)
        if not email:
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if href.lower().startswith("mailto:"):
                    raw_email = unquote(href[7:]).split("?")[0].strip().lower()
                    if "@" in raw_email and not any(raw_email.endswith(dom) for dom in IGNORED_EMAIL_DOMAINS):
                        email = raw_email
                        evidence_items.append({
                            "field_name": "email",
                            "field_value": email,
                            "source_url": p_url,
                            "evidence_excerpt": f"Published mailto link: {raw_email}",
                            "verification_status": "verified",
                        })
                        break

    # Fallback: Extract from text
    if not phone:
        for ph in PHONE_RE.findall(all_text):
            norm = normalize_indian_phone(ph)
            if norm:
                phone = norm
                evidence_items.append({
                    "field_name": "phone",
                    "field_value": phone,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published phone found in page body: {ph}",
                    "verification_status": "verified",
                })
                break

    if not email:
        for em in EMAIL_RE.findall(all_text):
            clean_em = em.lower()
            if not any(clean_em.endswith(dom) for dom in IGNORED_EMAIL_DOMAINS):
                email = clean_em
                evidence_items.append({
                    "field_name": "email",
                    "field_value": email,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published email in page text: {em}",
                    "verification_status": "verified",
                })
                break

    # 2. Extract company age / founding year
    found_match = FOUNDED_RE.search(all_text)
    if found_match:
        year = found_match.group(1)
        company_age = f"Founded {year}"
        evidence_items.append({
            "field_name": "company_age",
            "field_value": company_age,
            "source_url": root_url,
            "evidence_excerpt": found_match.group(0),
            "verification_status": "verified",
        })

    # 3. Extract company size / team size
    team_match = TEAM_SIZE_RE.search(all_text)
    if team_match:
        company_size = team_match.group(1)
        evidence_items.append({
            "field_name": "company_size",
            "field_value": company_size,
            "source_url": root_url,
            "evidence_excerpt": team_match.group(0),
            "verification_status": "verified",
        })

    # 4. Extract publicly listed leadership / contact person from About/Team pages
    about_pages = [p for p in crawled_pages if p.get("page_type") in ("about", "contact")]
    for p in about_pages:
        txt = p.get("text", "")
        role_match = LEADERSHIP_ROLES.search(txt)
        if role_match:
            # Look at adjacent window for potential person name
            start = max(0, role_match.start() - 40)
            end = min(len(txt), role_match.end() + 40)
            snippet = txt[start:end]
            contact_role = role_match.group(1).title()
            # Basic title-cased name extraction near role
            name_candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", snippet)
            if name_candidates:
                contact_person = name_candidates[0]
                evidence_items.append({
                    "field_name": "contact_person",
                    "field_value": f"{contact_person} ({contact_role})",
                    "source_url": p.get("url", root_url),
                    "evidence_excerpt": snippet.strip(),
                    "verification_status": "verified",
                })
                break

    return {
        "company_name": company_name,
        "industry_category": industry_category,
        "country": country or "India",
        "state": state,
        "city": city,
        "locality": locality,
        "website": root_url,
        "phone": phone,
        "email": email,
        "contact_person": contact_person,
        "contact_role": contact_role,
        "company_size": company_size,
        "company_age": company_age,
        "extracted_at": now,
        "evidence_items": evidence_items,
    }

