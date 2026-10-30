"""End-to-end geographical discovery and qualification pipeline."""
from __future__ import annotations

import time
from typing import Any

from app.config import REQUEST_DELAY_SECONDS
from app.services.dedupe import deduplicate
from app.services.discovery import discover_businesses_with_stats
from app.services.enrichment import enrich_website
from app.services.exporter import export_csv
from app.services.scoring import score_lead
from app.services.validation import validate_lead


def run_pipeline(
    city: str,
    category: str = "Digital Marketing",
    limit: int = 25,
    state: str = "",
) -> dict[str, Any]:
    """Execute discovery, indexed deduplication, website enrichment, validation, and export."""
    clean_city = city.strip()
    clean_category = (category or "Digital Marketing").strip()
    clean_state = state.strip()

    print(
        f"[pipeline] Starting run for city={clean_city!r}, "
        f"state={clean_state!r}, category={clean_category!r}, limit={limit}"
    )

    # 1. Geographic resolution & multi-source discovery (OSM + 6 alternative resources)
    discovery_res = discover_businesses_with_stats(
        city=clean_city,
        limit=limit,
        category=clean_category,
        state=clean_state,
    )
    discovered_candidates = discovery_res.businesses
    raw_discovered_count = sum(
        stat.get("raw", 0) for stat in discovery_res.source_stats.values()
    ) or len(discovered_candidates)

    # 2. Indexed deduplication before website enrichment to avoid duplicate HTTP requests
    unique_candidates = deduplicate(discovered_candidates)

    processed: list[dict[str, Any]] = []

    # 3. Public website enrichment, contact validation, and ICP scoring
    for item in unique_candidates[:limit]:
        item["sector"] = clean_category
        website = item.get("website", "")

        # Only request website enrichment if a website URL is available
        if website:
            enrichment = enrich_website(website)
            if enrichment.get("phone") and not item.get("phone"):
                item["phone"] = enrichment["phone"]
            if enrichment.get("email") and not item.get("email"):
                item["email"] = enrichment["email"]

            if enrichment.get("website_verified"):
                item["_website_verified"] = True

            ev_list = item.setdefault("evidence", [])
            for ev in enrichment.get("evidence", []):
                if ev and ev not in ev_list:
                    ev_list.append(ev)

            # Politeness delay only between live website network fetches
            if not enrichment.get("robots_status", "").startswith("robots.txt check"):
                time.sleep(min(REQUEST_DELAY_SECONDS, 0.5))

        # 4. Contact validation
        item = validate_lead(item)

        # 5. ICP scoring using preserved formula and weights
        score, reason = score_lead(item)
        item["lead_quality_score"] = score
        item["score_reason"] = reason

        processed.append(item)

    # 6. Final deduplication and prioritization
    final_leads = deduplicate(processed)
    final_leads.sort(
        key=lambda l: (
            l.get("lead_quality_score", 0),
            bool(l.get("phone")),
            bool(l.get("email")),
            bool(l.get("website")),
        ),
        reverse=True,
    )
    final_leads = final_leads[:limit]

    # 7. CSV Export
    filename = (
        f"{clean_city.lower().replace(' ', '_')}_"
        f"{clean_category.lower().replace(' ', '_')}_leads.csv"
    )
    csv_file = export_csv(final_leads, filename)

    # 8. Clean internal underscore-prefixed fields for public API response
    public_leads = []
    for lead in final_leads:
        public_leads.append({
            key: value
            for key, value in lead.items()
            if not key.startswith("_")
        })

    print(
        f"[pipeline] Completed: {len(public_leads)} qualified leads exported to {csv_file} "
        f"(raw discovered: {raw_discovered_count})"
    )

    return {
        "requested_city": clean_city,
        "requested_category": clean_category,
        "discovered": max(raw_discovered_count, len(public_leads)),
        "qualified": len(public_leads),
        "leads": public_leads,
        "csv_file": csv_file,
    }
