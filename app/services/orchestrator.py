"""Autonomous Public-Web Discovery Orchestrator executing Stages 1 to 10."""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import (
    CRAWLER_MAX_CONCURRENCY,
    DISCOVERY_MAX_QUERIES,
    DISCOVERY_MAX_URLS,
    get_industry_config,
)
from app.services.crawler import crawl_website
from app.services.dedupe import IndexedDeduplicator
from app.services.exporter import export_csv
from app.services.extraction import extract_business_data
from app.services.industry_classifier import classify_industry
from app.services.location_verifier import verify_location
from app.services.persistence import (
    create_research_run,
    get_latest_checkpoint,
    save_checkpoint,
    save_company,
    update_research_run,
)
from app.services.public_web_discovery import PublicWebDiscoveryGateway
from app.services.query_generator import generate_discovery_queries
from app.services.url_frontier import UrlFrontier
from app.services.validation import validate_lead


def execute_autonomous_run(
    city: str,
    category: str = "Digital Marketing",
    limit: int = 25,
    state: str = "",
    country: str = "India",
    locality: str = "",
    run_id: Optional[str] = None,
    trigger_type: str = "api",
) -> dict[str, Any]:
    """Execute end-to-end autonomous business discovery, crawling, extraction, and verification without ICP scoring."""
    start_time = time.monotonic()
    clean_city = (city or "").strip()
    clean_category = (category or "Digital Marketing").strip()
    clean_state = (state or "").strip()
    clean_country = (country or "India").strip()
    clean_locality = (locality or "").strip()

    if not clean_city:
        raise ValueError("City name is mandatory for geographical discovery.")

    # 1. Initialize or load run state
    if not run_id:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        create_research_run(
            run_id=run_id,
            industry=clean_category,
            city=clean_city,
            state=clean_state,
            country=clean_country,
            locality=clean_locality,
            trigger_type=trigger_type,
        )

    print(f"\n[orchestrator] Starting autonomous research run {run_id} for {clean_category} in {clean_city}, {clean_state}...")
    update_research_run(run_id=run_id, execution_status="running")

    # Check for resume checkpoint
    latest_checkpoint = get_latest_checkpoint(run_id)
    if latest_checkpoint:
        print(f"[orchestrator] Resuming from checkpoint stage: {latest_checkpoint.get('stage')}")

    frontier = UrlFrontier(run_id=run_id)
    gateway = PublicWebDiscoveryGateway()

    # 2. Stage 2: Generate industry & location discovery queries
    queries = generate_discovery_queries(
        industry=clean_category,
        city=clean_city,
        state=clean_state,
        country=clean_country,
        locality=clean_locality,
        max_queries=DISCOVERY_MAX_QUERIES,
    )
    save_checkpoint(run_id, "queries_generated", checkpoint_data={"query_count": len(queries)})

    # 3. Stage 3 & 4: Discover candidate URLs via generic gateway & policy filtering
    discovered_urls = gateway.run_discovery(queries, max_urls=max(limit * 3, DISCOVERY_MAX_URLS))
    urls_discovered_count = len(discovered_urls)
    print(f"[orchestrator] Discovered {urls_discovered_count} candidate URLs across public web gateway.")

    for item in discovered_urls:
        frontier.add_url(
            raw_url=item["url"],
            depth=0,
            query=item.get("query", ""),
            discovery_method=item.get("method", "public_web"),
            relevance_status="approved",
        )

    update_research_run(run_id=run_id, urls_discovered=urls_discovered_count)
    save_checkpoint(run_id, "urls_discovered", checkpoint_data={"count": urls_discovered_count})

    # 4. Stage 5: Crawl approved websites and follow internal pages
    pending_items = frontier.fetch_batch(batch_size=max(limit * 2, 30))
    urls_to_crawl = [item["url"] for item in pending_items]
    crawled_results: list[dict[str, Any]] = []

    def _crawl_worker(url: str) -> dict[str, Any]:
        return crawl_website(url)

    concurrency = min(CRAWLER_MAX_CONCURRENCY, len(urls_to_crawl)) if urls_to_crawl else 1
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            crawled_results = list(executor.map(_crawl_worker, urls_to_crawl))
    else:
        crawled_results = [_crawl_worker(u) for u in urls_to_crawl]

    urls_crawled_count = sum(1 for res in crawled_results if res.get("status") == "completed")
    print(f"[orchestrator] Crawled {urls_crawled_count}/{len(urls_to_crawl)} websites successfully.")
    update_research_run(run_id=run_id, urls_crawled=urls_crawled_count)
    save_checkpoint(run_id, "websites_crawled", checkpoint_data={"count": urls_crawled_count})

    # Update frontier items status
    for item, res in zip(pending_items, crawled_results):
        fid = item.get("frontier_id")
        if fid:
            if res.get("status") == "completed":
                frontier.mark_completed(fid)
            elif res.get("status") == "blocked":
                frontier.mark_blocked(fid, res.get("error", "blocked"))
            else:
                frontier.mark_failed(fid, res.get("error", "failed"))

    # 5. Stage 6A, 6B, 7 & 8: Classification, Location Verification, Extraction, and Validation
    identified_businesses: list[dict[str, Any]] = []

    for crawl_res in crawled_results:
        if crawl_res.get("status") != "completed" or not crawl_res.get("crawled_pages"):
            continue

        root_url = crawl_res["root_url"]
        pages = crawl_res["crawled_pages"]
        combined_text = crawl_res["combined_text"]
        titles = crawl_res["page_titles"]

        # Stage 6A: Industry Identification
        industry_res = classify_industry(
            company_name="",
            combined_text=combined_text,
            page_titles=titles,
            industry_category=clean_category,
        )
        if not industry_res.get("is_match"):
            continue

        # Stage 6B: Location Verification
        location_res = verify_location(
            city=clean_city,
            state=clean_state,
            country=clean_country,
            locality=clean_locality,
            crawled_pages=pages,
        )
        if not location_res.get("verified") and location_res.get("location_type") not in ("headquarters", "branch", "service_area"):
            continue

        # Stage 7: Business Data Extraction
        biz_data = extract_business_data(
            root_url=root_url,
            crawled_pages=pages,
            industry_category=industry_res.get("industry_category", clean_category),
            city=clean_city,
            state=clean_state,
            country=clean_country,
            locality=location_res.get("locality") or clean_locality,
        )

        biz_data["industry_subcategory"] = industry_res.get("subcategory", "")
        biz_data["services"] = industry_res.get("services", [])
        biz_data["location_type"] = location_res.get("location_type", "unverified")
        biz_data["source"] = "Public Web Discovery"

        # Evidence tracking
        if industry_res.get("evidence_excerpt"):
            biz_data.setdefault("evidence_items", []).append({
                "field_name": "industry_classification",
                "field_value": industry_res["subcategory"],
                "source_url": root_url,
                "evidence_excerpt": industry_res["evidence_excerpt"],
                "verification_status": "verified",
            })

        if location_res.get("evidence_excerpt"):
            biz_data.setdefault("evidence_items", []).append({
                "field_name": "location_verification",
                "field_value": f"{clean_city} ({location_res['location_type']})",
                "source_url": location_res.get("source_url") or root_url,
                "evidence_excerpt": location_res["evidence_excerpt"],
                "verification_status": "verified",
            })

        # Stage 8: Data Validation & Quality Control
        validated_record = validate_lead(biz_data)

        # Do NOT invoke Dakini ICP scoring. Keep quality score at 0 or confidence.
        validated_record["lead_quality_score"] = 0
        validated_record["score_reason"] = "ICP scoring excluded by autonomous discovery policy"

        # Add flat evidence array for schema compatibility
        ev_list = [ev["evidence_excerpt"] for ev in validated_record.get("evidence_items", []) if ev.get("evidence_excerpt")]
        validated_record["evidence"] = ev_list

        identified_businesses.append(validated_record)

    # 6. Deduplication and Master Database Persistence (Stage 9)
    deduper = IndexedDeduplicator()
    for b in identified_businesses:
        deduper.add_or_merge(b)
    canonical_leads = deduper.get_results()

    for lead in canonical_leads:
        save_company(lead)

    # Prioritize leads with verified contacts and headquarters/branches
    canonical_leads.sort(
        key=lambda x: (
            x.get("location_type") == "headquarters",
            x.get("location_type") == "branch",
            bool(x.get("phone")),
            bool(x.get("email")),
            bool(x.get("website")),
        ),
        reverse=True,
    )
    final_leads = canonical_leads[:limit]

    # 7. Stage 10: Structured Export
    clean_city_slug = clean_city.lower().replace(" ", "_")
    clean_cat_slug = clean_category.lower().replace(" ", "_")
    csv_filename = f"{clean_city_slug}_{clean_cat_slug}_leads.csv"
    export_path = export_csv(final_leads, csv_filename)

    duration = round(time.monotonic() - start_time, 2)
    update_research_run(
        run_id=run_id,
        execution_status="completed",
        completed_at=datetime.now(timezone.utc).isoformat(),
        businesses_identified=len(canonical_leads),
        businesses_validated=len(final_leads),
        export_location=export_path,
    )
    save_checkpoint(run_id, "completed", checkpoint_data={"duration_seconds": duration, "leads_exported": len(final_leads)})

    print(
        f"[orchestrator] Run {run_id} completed in {duration}s: "
        f"{len(final_leads)} verified businesses exported to {export_path}."
    )

    # Clean internal underscore keys for public API response
    public_leads = []
    for lead in final_leads:
        public_leads.append({
            k: v for k, v in lead.items() if not k.startswith("_") and k != "evidence_items"
        })

    return {
        "run_id": run_id,
        "requested_city": clean_city,
        "requested_category": clean_category,
        "discovered": max(urls_discovered_count, len(public_leads)),
        "qualified": len(public_leads),
        "leads": public_leads,
        "csv_file": export_path,
    }
