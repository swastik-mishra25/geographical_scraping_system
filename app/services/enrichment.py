"""Public website enrichment with politeness, robots compliance, and contact extraction."""
from __future__ import annotations

import re
import threading
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import (
    ENRICHMENT_CONNECT_TIMEOUT,
    ENRICHMENT_READ_TIMEOUT,
    HEADERS,
)
from app.services.robots import allowed_by_robots

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

PHONE_RE = re.compile(
    r"(?:(?:\+|0{0,2})91[\s.-]?)?(?:[6-9]\d{4}[\s.-]?\d{5}|[6-9]\d{9})\b"
)

IGNORED_EMAIL_DOMAINS = {
    "example.com",
    "domain.com",
    "yourdomain.com",
    "sentry.io",
    "wixpress.com",
    "wordpress.org",
    "schema.org",
}

IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    ".ico",
    ".css",
    ".js",
}

_ENRICHMENT_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

_SESSION = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=64,
    pool_maxsize=64,
    max_retries=Retry(total=1, backoff_factor=0.2, status_forcelist=[502, 503, 504]),
)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)
_SESSION.headers.update(HEADERS)


def normalize_phone(value: str) -> str:
    """Normalize Indian mobile number to +91XXXXXXXXXX format."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return ""


def _is_valid_email(email: str) -> bool:
    """Filter out placeholders, assets, and malformed emails."""
    clean = email.strip().lower()
    if not clean or "@" not in clean:
        return False
    if any(clean.endswith(ext) for ext in IGNORED_EXTENSIONS):
        return False
    user, domain = clean.split("@", 1)
    if not user or not domain or "." not in domain:
        return False
    if domain in IGNORED_EMAIL_DOMAINS:
        return False
    return True


def _extract_from_soup(
    soup: BeautifulSoup, source_page_url: str
) -> tuple[str, str, list[str]]:
    """Extract official phone and email from tel/mailto links and page text."""
    phone = ""
    email = ""
    evidence: list[str] = []

    # 1. Inspect tel: links (highest accuracy for phone)
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.lower().startswith("tel:"):
            raw_phone = unquote(href[4:])
            norm = normalize_phone(raw_phone)
            if norm:
                phone = norm
                evidence.append(f"Official phone extracted from tel link on {source_page_url}")
                break

    # 2. Inspect mailto: links (highest accuracy for email)
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.lower().startswith("mailto:"):
            raw_email = unquote(href[7:]).split("?")[0].strip()
            if _is_valid_email(raw_email):
                email = raw_email.lower()
                evidence.append(f"Official email extracted from mailto link on {source_page_url}")
                break

    # 3. Fallback: Parse body text
    body_text = soup.get_text(" ", strip=True)

    if not email:
        for em in EMAIL_RE.findall(body_text):
            if _is_valid_email(em):
                email = em.lower()
                evidence.append(f"Official email located on {source_page_url}")
                break

    if not phone:
        for ph in PHONE_RE.findall(body_text):
            norm = normalize_phone(ph)
            if norm:
                phone = norm
                evidence.append(f"Official phone located on {source_page_url}")
                break

    return phone, email, evidence


def enrich_website(url: str) -> dict[str, Any]:
    """Inspect official company website homepage and contact page for published details."""
    clean_url = (url or "").strip()
    if not clean_url:
        return {
            "phone": "",
            "email": "",
            "title": "",
            "evidence": [],
            "robots_status": "No website",
            "website_verified": False,
        }

    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    # Check memory cache
    try:
        domain_key = urlsplit(clean_url).netloc.lower()
    except Exception:
        domain_key = clean_url.lower()

    with _CACHE_LOCK:
        if domain_key in _ENRICHMENT_CACHE:
            return dict(_ENRICHMENT_CACHE[domain_key])

    allowed, robots_status = allowed_by_robots(clean_url)
    if not allowed:
        res = {
            "phone": "",
            "email": "",
            "title": "",
            "evidence": [robots_status],
            "robots_status": robots_status,
            "website_verified": False,
        }
        with _CACHE_LOCK:
            _ENRICHMENT_CACHE[domain_key] = res
        return res

    phone = ""
    email = ""
    title = ""
    evidence = ["Public homepage inspected", robots_status]
    contact_url = ""

    try:
        response = _SESSION.get(
            clean_url,
            timeout=(ENRICHMENT_CONNECT_TIMEOUT, ENRICHMENT_READ_TIMEOUT),
            allow_redirects=True,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""

        ph, em, ev = _extract_from_soup(soup, "homepage")
        if ph:
            phone = ph
        if em:
            email = em
        evidence.extend(ev)

        # Look for contact / about page
        for link in soup.find_all("a", href=True):
            label = link.get_text(" ", strip=True).lower()
            href = link.get("href", "").lower()
            if any(term in label or term in href for term in ("contact", "get-in-touch", "reach-us")):
                contact_url = urljoin(response.url, link["href"])
                break

    except Exception as exc:
        evidence.append(f"Website request error: {type(exc).__name__}")

    # Inspect contact page if phone or email is still missing
    if contact_url and (not phone or not email):
        contact_allowed, contact_robots = allowed_by_robots(contact_url)
        if contact_allowed:
            try:
                contact_resp = _SESSION.get(
                    contact_url,
                    timeout=(2.0, 3.5),
                )
                if contact_resp.ok:
                    contact_soup = BeautifulSoup(contact_resp.text, "html.parser")
                    c_phone, c_email, c_ev = _extract_from_soup(contact_soup, "contact page")
                    if not phone and c_phone:
                        phone = c_phone
                    if not email and c_email:
                        email = c_email
                    evidence.append("Public contact page inspected")
                    evidence.extend(c_ev)
            except Exception:
                pass
        else:
            evidence.append(contact_robots)

    website_verified = bool(phone or email)
    result = {
        "phone": phone,
        "email": email,
        "title": title,
        "evidence": evidence,
        "robots_status": robots_status,
        "website_verified": website_verified,
    }
    with _CACHE_LOCK:
        _ENRICHMENT_CACHE[domain_key] = result
    return result
