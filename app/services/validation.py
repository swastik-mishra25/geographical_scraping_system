import re
from urllib.parse import urlparse


def validate_lead(lead: dict) -> dict:
    website = lead.get("website", "").strip()
    phone = lead.get("phone", "").strip()
    email = lead.get("email", "").strip()

    website_valid = False
    if website:
        try:
            parsed = urlparse(
                website if "://" in website else "https://" + website
            )
            website_valid = bool(parsed.netloc)
        except Exception:
            website_valid = False

    phone_valid = bool(re.fullmatch(r"\+91[6-9]\d{9}", phone))
    email_valid = bool(
        re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            email,
        )
    )

    checks = []

    if website_valid:
        checks.append("website format valid")

    if phone_valid:
        checks.append("+91 Indian phone format valid")

    if email_valid:
        checks.append("public email format valid")

    if not checks:
        checks.append("no validated contact found")

    lead["contact_validation"] = "; ".join(checks)
    lead["_website_valid"] = website_valid
    lead["_phone_valid"] = phone_valid
    lead["_email_valid"] = email_valid

    return lead
