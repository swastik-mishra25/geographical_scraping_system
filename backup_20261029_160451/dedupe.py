import re
from urllib.parse import urlparse


def domain(value: str) -> str:
    if not value:
        return ""

    parsed = urlparse(
        value if "://" in value else "https://" + value
    )

    host = parsed.netloc.lower()
    host = host.removeprefix("www.")
    return host


def normalize_name(value: str) -> str:
    value = value.casefold()
    return re.sub(r"[^a-z0-9]", "", value)


def deduplicate(leads: list[dict]) -> list[dict]:
    seen = set()
    result = []

    # Higher-scored records win when duplicates exist.
    ordered = sorted(
        leads,
        key=lambda x: x.get("lead_quality_score", 0),
        reverse=True,
    )

    for lead in ordered:
        name_key = normalize_name(lead.get("company_name", ""))
        domain_key = domain(lead.get("website", ""))

        key = domain_key or name_key

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(lead)

    return result
