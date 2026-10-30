import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import HEADERS
from app.services.robots import allowed_by_robots

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

PHONE_RE = re.compile(
    r"(?:\+91[\s.-]?)?(?:[6-9]\d{9})"
)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")

    if digits.startswith("91") and len(digits) == 12:
        return "+" + digits

    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits

    return ""


def _extract_contact(text: str) -> tuple[str, str]:
    emails = EMAIL_RE.findall(text)
    phones = PHONE_RE.findall(text)

    email = emails[0] if emails else ""
    phone = ""

    for raw_phone in phones:
        normalized = normalize_phone(raw_phone)
        if normalized:
            phone = normalized
            break

    return phone, email


def enrich_website(url: str) -> dict:
    if not url:
        return {
            "phone": "",
            "email": "",
            "title": "",
            "evidence": [],
            "robots_status": "No website",
        }

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    allowed, robots_status = allowed_by_robots(url)

    if not allowed:
        return {
            "phone": "",
            "email": "",
            "title": "",
            "evidence": [robots_status],
            "robots_status": robots_status,
        }

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "phone": "",
            "email": "",
            "title": "",
            "evidence": [f"Website request failed: {exc}"],
            "robots_status": robots_status,
        }

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    phone, email = _extract_contact(text)
    title = soup.title.get_text(strip=True) if soup.title else ""

    evidence = [
        "Public homepage inspected",
        robots_status,
    ]

    # Find one public contact page and enrich from it if needed.
    contact_url = ""
    for link in soup.find_all("a", href=True):
        label = link.get_text(" ", strip=True).lower()
        href = link.get("href", "").lower()

        if "contact" in label or "contact" in href:
            contact_url = urljoin(response.url, link["href"])
            break

    if contact_url and (not phone or not email):
        contact_allowed, contact_robots = allowed_by_robots(contact_url)

        if contact_allowed:
            try:
                contact_response = requests.get(
                    contact_url,
                    headers=HEADERS,
                    timeout=15,
                )
                contact_response.raise_for_status()

                contact_soup = BeautifulSoup(
                    contact_response.text,
                    "html.parser",
                )
                contact_text = contact_soup.get_text(" ", strip=True)

                contact_phone, contact_email = _extract_contact(contact_text)

                if not phone:
                    phone = contact_phone

                if not email:
                    email = contact_email

                evidence.append("Public contact page inspected")
            except requests.RequestException:
                pass
        else:
            evidence.append(contact_robots)

    return {
        "phone": phone,
        "email": email,
        "title": title,
        "evidence": evidence,
        "robots_status": robots_status,
    }
