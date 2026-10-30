def score_lead(lead: dict) -> tuple[int, str]:
    score = 0
    reasons = []

    if lead.get("_website_valid"):
        score += 25
        reasons.append("website available")

    if lead.get("_phone_valid"):
        score += 25
        reasons.append("valid Indian business phone")

    if lead.get("_email_valid"):
        score += 15
        reasons.append("public business email")

    combined = (
        f"{lead.get('company_name', '')} "
        f"{lead.get('sector', '')}"
    ).lower()

    if any(
        term in combined
        for term in ("marketing", "digital", "advertising", "media")
    ):
        score += 25
        reasons.append("marketing relevance")

    if lead.get("city"):
        score += 10
        reasons.append("geographic match")

    return min(score, 100), "; ".join(reasons)
