import time

from app.config import REQUEST_DELAY_SECONDS
from app.services.discovery import discover_businesses
from app.services.enrichment import enrich_website
from app.services.validation import validate_lead
from app.services.scoring import score_lead
from app.services.dedupe import deduplicate
from app.services.exporter import export_csv


def run_pipeline(city: str, category: str, limit: int) -> dict:
    discovered = discover_businesses(city, limit)

    processed = []

    for item in discovered:
        item["sector"] = category

        enrichment = enrich_website(item.get("website", ""))

        if enrichment["phone"]:
            item["phone"] = enrichment["phone"]

        if enrichment["email"]:
            item["email"] = enrichment["email"]

        item["evidence"] = enrichment["evidence"]

        item = validate_lead(item)

        score, reason = score_lead(item)
        item["lead_quality_score"] = score
        item["score_reason"] = reason

        processed.append(item)

        time.sleep(REQUEST_DELAY_SECONDS)

    unique = deduplicate(processed)

    filename = (
        f"{city.lower().replace(' ', '_')}_"
        f"{category.lower().replace(' ', '_')}_leads.csv"
    )

    csv_file = export_csv(unique, filename)

    # Remove internal fields from API response.
    public_leads = []
    for lead in unique:
        public_leads.append({
            key: value
            for key, value in lead.items()
            if not key.startswith("_")
        })

    return {
        "requested_city": city,
        "requested_category": category,
        "discovered": len(discovered),
        "qualified": len(public_leads),
        "leads": public_leads,
        "csv_file": csv_file,
    }
