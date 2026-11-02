"""Autonomous Public-Web Discovery Orchestrator executing Stages 1 to 10."""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import (
    CRAWLER_MAX_CONCURRENCY,
    DATA_DIR,
    DISCOVERY_MAX_QUERIES,
    DISCOVERY_MAX_URLS,
    get_industry_config,
)
from app.services.crawler import crawl_website
from app.services.dedupe import IndexedDeduplicator
from app.services.exporter import export_csv, export_discovery_csv
from app.services.extraction import extract_business_data
from app.services.industry_classifier import classify_industry
from app.services.location_verifier import verify_location
from app.services.persistence import (
    create_research_run,
    get_latest_checkpoint,
    save_checkpoint,
    save_companies_batch,
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
    scaled_queries_count = max(DISCOVERY_MAX_QUERIES, min(50, max(8, limit // 4)))
    queries = generate_discovery_queries(
        industry=clean_category,
        city=clean_city,
        state=clean_state,
        country=clean_country,
        locality=clean_locality,
        max_queries=scaled_queries_count,
    )
    save_checkpoint(run_id, "queries_generated", checkpoint_data={"query_count": len(queries)})

    # 3. Stage 3 & 4: Discover candidate URLs via generic gateway & policy filtering
    target_max_urls = min(10000, max(limit + 50, int(limit * 1.25))) if limit < 8000 else 10000
    discovered_urls = gateway.run_discovery(
        queries,
        max_urls=target_max_urls,
        city=clean_city,
        category=clean_category,
    )
    urls_discovered_count = len(discovered_urls)
    print(f"[orchestrator] Discovered {urls_discovered_count} candidate URLs across public web gateway.", flush=True)

    frontier.add_urls_batch(discovered_urls)

    update_research_run(run_id=run_id, urls_discovered=urls_discovered_count)
    save_checkpoint(run_id, "urls_discovered", checkpoint_data={"count": urls_discovered_count})

    # 4. Stage 5: Crawl approved websites and follow internal pages
    pending_items = frontier.fetch_batch(batch_size=target_max_urls)
    urls_to_crawl = [item["url"] for item in pending_items]
    crawled_results: list[dict[str, Any]] = []

    def _crawl_worker(url: str) -> dict[str, Any]:
        return crawl_website(url)

    concurrency = min(24, max(4, len(urls_to_crawl) // 10)) if urls_to_crawl else 1
    print(f"[orchestrator] Crawling {len(urls_to_crawl)} websites in parallel (concurrency={concurrency})...", flush=True)
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            crawled_results = list(executor.map(_crawl_worker, urls_to_crawl))
    else:
        crawled_results = [_crawl_worker(u) for u in urls_to_crawl]

    urls_crawled_count = sum(1 for res in crawled_results if res.get("status") == "completed")
    print(f"[orchestrator] Crawled {urls_crawled_count}/{len(urls_to_crawl)} websites successfully.", flush=True)

    update_research_run(run_id=run_id, urls_crawled=urls_crawled_count)
    save_checkpoint(run_id, "websites_crawled", checkpoint_data={"count": urls_crawled_count})

    # Update frontier items status in a single batch
    frontier_updates = []
    for item, res in zip(pending_items, crawled_results):
        fid = item.get("frontier_id")
        if fid:
            st = res.get("status")
            if st == "completed":
                frontier_updates.append(("completed", "", fid))
            elif st == "blocked":
                frontier_updates.append(("blocked", res.get("error", "blocked"), fid))
            else:
                frontier_updates.append(("failed", res.get("error", "failed"), fid))
    if frontier_updates:
        frontier.mark_batch(frontier_updates)

    # 5. Stage 6A, 6B, 7 & 8: Classification, Location Verification, Extraction, and Validation
    identified_businesses: list[dict[str, Any]] = []
    evaluated_discovery: list[dict[str, Any]] = []

    discovered_lookup = {item["url"]: dict(item) for item in discovered_urls}
    for item in pending_items:
        if item.get("url"):
            discovered_lookup.setdefault(item["url"], dict(item))

    for pending_item, crawl_res in zip(pending_items, crawled_results):
        url = pending_item.get("url") or crawl_res.get("root_url") or ""
        meta = discovered_lookup.get(url, {})
        dom = meta.get("domain", "")
        q_used = meta.get("query", "")
        m_used = meta.get("method", "public_web")
        t_init = meta.get("title", "")

        if crawl_res.get("status") != "completed":
            evaluated_discovery.append({
                "url": url,
                "domain": dom,
                "query": q_used,
                "method": m_used,
                "title": t_init,
                "crawl_status": crawl_res.get("status", "failed"),
                "pipeline_status": f"crawl_{crawl_res.get('status', 'failed')}",
                "industry_match": False,
                "location_verified": False,
                "location_type": "unverified",
                "company_name": "",
                "reason": crawl_res.get("error", "Crawl failed or blocked"),
            })
            continue

        if not crawl_res.get("crawled_pages"):
            evaluated_discovery.append({
                "url": url,
                "domain": dom,
                "query": q_used,
                "method": m_used,
                "title": t_init,
                "crawl_status": "completed",
                "pipeline_status": "no_pages_extracted",
                "industry_match": False,
                "location_verified": False,
                "location_type": "unverified",
                "company_name": "",
                "reason": "No pages extracted during crawl",
            })
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
            evaluated_discovery.append({
                "url": root_url,
                "domain": dom,
                "query": q_used,
                "method": m_used,
                "title": titles[0] if titles else t_init,
                "crawl_status": "completed",
                "pipeline_status": "disqualified_industry",
                "industry_match": False,
                "location_verified": False,
                "location_type": "unverified",
                "company_name": "",
                "reason": f"Content did not match industry '{clean_category}'",
            })
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
            evaluated_discovery.append({
                "url": root_url,
                "domain": dom,
                "query": q_used,
                "method": m_used,
                "title": titles[0] if titles else t_init,
                "crawl_status": "completed",
                "pipeline_status": "disqualified_location",
                "industry_match": True,
                "location_verified": False,
                "location_type": location_res.get("location_type", "unverified"),
                "company_name": "",
                "reason": f"Location unverified for city '{clean_city}'",
            })
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

        evaluated_discovery.append({
            "url": root_url,
            "domain": dom,
            "query": q_used,
            "method": m_used,
            "title": biz_data.get("company_name") or (titles[0] if titles else t_init),
            "crawl_status": "completed",
            "pipeline_status": "qualified",
            "industry_match": True,
            "location_verified": True,
            "location_type": location_res.get("location_type", "headquarters"),
            "company_name": biz_data.get("company_name", ""),
            "reason": f"Verified {clean_category} in {clean_city}",
        })

    # Append any candidate URLs discovered but not crawled in this batch
    crawled_urls = {item.get("url") for item in pending_items}
    for item in discovered_urls:
        if item.get("url") not in crawled_urls:
            evaluated_discovery.append({
                "url": item.get("url", ""),
                "domain": item.get("domain", ""),
                "query": item.get("query", ""),
                "method": item.get("method", "public_web"),
                "title": item.get("title", ""),
                "crawl_status": "queued",
                "pipeline_status": "discovery_candidate",
                "industry_match": False,
                "location_verified": False,
                "location_type": "unverified",
                "company_name": "",
                "reason": "Candidate URL discovered from public web gateway",
            })

    # 6. Deduplication and Master Database Persistence (Stage 9)
    deduper = IndexedDeduplicator()
    for b in identified_businesses:
        deduper.add_or_merge(b)
    canonical_leads = deduper.get_results()

    save_companies_batch(canonical_leads)

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

    # Export all candidate discovery data
    discovery_csv_filename = f"{clean_city_slug}_{clean_cat_slug}_discovery_all.csv"
    discovery_export_path = export_discovery_csv(evaluated_discovery, discovery_csv_filename)

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
        f"{len(final_leads)} verified businesses exported to {export_path}, "
        f"{len(evaluated_discovery)} discovery candidates exported to {discovery_export_path}.",
        flush=True,
    )

    # Clean internal underscore keys for public API response
    public_leads = []
    for lead in final_leads:
        public_leads.append({
            k: v for k, v in lead.items() if not k.startswith("_") and k != "evidence_items"
        })

    master_excel = str(DATA_DIR / "companies_leads.xlsx").replace("\\", "/")

    return {
        "run_id": run_id,
        "requested_city": clean_city,
        "requested_category": clean_category,
        "discovered": max(urls_discovered_count, len(evaluated_discovery), len(public_leads)),
        "qualified": len(public_leads),
        "leads": public_leads,
        "discovery_data": evaluated_discovery,
        "csv_file": export_path,
        "discovery_csv_file": discovery_export_path,
        "master_excel_file": master_excel,
    }
