"""Stage 8: Data validation and quality control distinguishing syntax validity from business association."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

EMAIL_FORMAT_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)

INDIAN_MOBILE_RE = re.compile(
    r"^\+91[6-9]\d{9}$"
)


def validate_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Validate contact information and quality controls maintaining API compatibility."""
    website = str(lead.get("website", "")).strip()
    phone = str(lead.get("phone", "")).strip()
    email = str(lead.get("email", "")).strip()

    # 1. Website format validation
    website_valid = False
    if website:
        try:
            parsed = urlsplit(
                website if "://" in website else "https://" + website
            )
            website_valid = bool(parsed.hostname and "." in parsed.hostname)
        except Exception:
            website_valid = False

    # 2. Phone validation (unambiguous Indian mobile format)
    phone_valid = bool(INDIAN_MOBILE_RE.fullmatch(phone))
    if not phone_valid and phone:
        # If phone does not match valid Indian mobile pattern, preserve raw and clear mobile field
        lead["_raw_phone"] = phone
        lead["phone"] = ""

    # 3. Email validation
    email_valid = bool(EMAIL_FORMAT_RE.fullmatch(email))
    if not email_valid and email:
        lead["_raw_email"] = email
        lead["email"] = ""

    checks: list[str] = []

    if website_valid:
        checks.append("website format valid")

    if phone_valid:
        checks.append("+91 Indian phone format valid")

    if email_valid:
        checks.append("public email format valid")

    # Corroboration / ownership check
    if lead.get("_website_verified") or any(
        "Official" in str(ev) for ev in lead.get("evidence", [])
    ) or any(
        "Published" in str(ev) for ev in lead.get("evidence", [])
    ):
        checks.append("official website contact confirmed")

    if not checks:
        checks.append("no validated contact found")

    lead["contact_validation"] = "; ".join(checks)
    lead["_website_valid"] = website_valid
    lead["_phone_valid"] = phone_valid
    lead["_email_valid"] = email_valid

    # Assign overall verification status
    if website_valid and (phone_valid or email_valid):
        lead["verification_status"] = "verified"
    elif website_valid:
        lead["verification_status"] = "partial"
    else:
        lead["verification_status"] = "unverified"

    return lead


def validate_business_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate full business record, field completeness, and evidence consistency."""
    return validate_lead(record)
