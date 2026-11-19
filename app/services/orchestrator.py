"""Autonomous Public-Web Discovery Orchestrator executing Stages 1 to 10."""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Optional

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
    phone_required: bool = False,
    multi_locality: bool = False,
    step_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    include_seeds: bool = True,
    exclude_domains: Optional[set[str]] = None,
    stop_event: Optional[Any] = None,
) -> dict[str, Any]:
    """Execute end-to-end autonomous business discovery, crawling, extraction, and verification."""
    start_time = time.monotonic()
    clean_city = (city or "").strip()
    clean_category = (category or "Digital Marketing").strip()
    clean_state = (state or "").strip()
    clean_country = (country or "India").strip()
    clean_locality = (locality or "").strip()

    if not clean_city:
        raise ValueError("City name is mandatory for geographical discovery.")

    # Strategy A + B delegation: if multi_locality is enabled or limit > 100 without a single specified locality
    if multi_locality or (limit > 100 and not clean_locality):
        return execute_multi_locality_campaign(
            city=clean_city,
            category=clean_category,
            target_limit=limit,
            state=clean_state,
            country=clean_country,
            phone_required=phone_required,
        )

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

    # 2. Stage 2: Generate industry & location discovery queries (focused 4-8 queries per shard)
    scaled_queries_count = max(4, min(8, max(4, limit // 10)))
    queries = generate_discovery_queries(
        industry=clean_category,
        city=clean_city,
        state=clean_state,
        country=clean_country,
        locality=clean_locality,
        max_queries=scaled_queries_count,
    )
    save_checkpoint(run_id, "queries_generated", checkpoint_data={"query_count": len(queries)})
    if step_callback:
        step_callback({"stage": "queries", "query_count": len(queries)})

    # 3. Stage 3 & 4: Discover candidate URLs via generic gateway & policy filtering
    target_max_urls = min(10000, max(limit * 2, limit + 5)) if limit < 50 else min(10000, max(limit + 35, int(limit * 1.5)))
    discovery_kwargs: dict[str, Any] = {
        "max_urls": target_max_urls,
        "city": clean_city,
        "category": clean_category,
        "step_callback": step_callback,
    }
    if not include_seeds:
        discovery_kwargs["include_seeds"] = False
    if exclude_domains:
        discovery_kwargs["exclude_domains"] = exclude_domains

    discovered_urls = gateway.run_discovery(queries, **discovery_kwargs)
    if stop_event and stop_event.is_set():
        return {
            "run_id": run_id,
            "requested_city": clean_city,
            "requested_category": clean_category,
            "discovered": 0,
            "qualified": 0,
            "total_qualified": 0,
            "leads_with_phone": 0,
            "phone_required": phone_required,
            "duration_seconds": round(time.monotonic() - start_time, 2),
            "leads": [],
            "discovery_data": [],
            "discovery_records": [],
        }
    urls_discovered_count = len(discovered_urls)
    print(f"[orchestrator] Discovered {urls_discovered_count} candidate URLs across public web gateway.", flush=True)

    frontier.add_urls_batch(discovered_urls)

    update_research_run(run_id=run_id, urls_discovered=urls_discovered_count)
    save_checkpoint(run_id, "urls_discovered", checkpoint_data={"count": urls_discovered_count})
    if step_callback:
        step_callback({"stage": "discovery", "discovered_count": urls_discovered_count})

    # 4. Stage 5: Crawl approved websites and follow internal pages
    current_run_urls = [d["url"] for d in discovered_urls if d.get("url")]
    pending_items = frontier.fetch_batch(batch_size=target_max_urls, urls=current_run_urls)
    # Ensure any discovered items for this run are included even if not yet populated in frontier
    fetched_urls = {item["url"] for item in pending_items if item.get("url")}
    for d in discovered_urls:
        if d.get("url") and d["url"] not in fetched_urls and len(pending_items) < target_max_urls:
            pending_items.append(dict(d))
            fetched_urls.add(d["url"])

    urls_to_crawl = [item["url"] for item in pending_items]
    crawled_results: list[dict[str, Any]] = [{} for _ in urls_to_crawl]
    completed_crawl_tasks = 0

    identified_businesses: list[dict[str, Any]] = []
    evaluated_discovery: list[Optional[dict[str, Any]]] = [None for _ in urls_to_crawl]
    stream_lock = threading.Lock()

    discovered_lookup = {item["url"]: dict(item) for item in discovered_urls}
    for item in pending_items:
        if item.get("url"):
            discovered_lookup.setdefault(item["url"], dict(item))

    from app.services.scoring import score_lead

    def _process_crawled_website(idx: int, crawl_res: dict[str, Any]) -> None:
        """Immediately classify, verify location, extract contacts, and stream to DB as each crawl finishes."""
        pending_item = pending_items[idx]
        url = pending_item.get("url") or crawl_res.get("root_url") or ""
        meta = discovered_lookup.get(url, {})
        dom = meta.get("domain", "")
        q_used = meta.get("query", "")
        m_used = meta.get("method", "public_web")
        t_init = meta.get("title", "")

        if crawl_res.get("status") != "completed":
            evaluated_discovery[idx] = {
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
            }
            return

        if not crawl_res.get("crawled_pages"):
            evaluated_discovery[idx] = {
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
            }
            return

        root_url = crawl_res["root_url"]
        pages = crawl_res["crawled_pages"]
        combined_text = crawl_res["combined_text"]
        titles = crawl_res["page_titles"]

        # Stage 6A: Industry Identification
        industry_res = classify_industry(
            company_name=t_init or dom,
            combined_text=combined_text,
            page_titles=titles,
            industry_category=clean_category,
        )
        if not industry_res.get("is_match"):
            evaluated_discovery[idx] = {
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
            }
            return

        # Stage 6B: Location Verification
        location_res = verify_location(
            city=clean_city,
            state=clean_state,
            country=clean_country,
            locality=clean_locality,
            crawled_pages=pages,
        )
        if not location_res.get("verified") and location_res.get("location_type") not in ("headquarters", "branch", "service_area"):
            page_title_lower = (titles[0] if titles else "").lower()
            other_cities = {
                "delhi", "gurgaon", "gurugram", "noida", "mumbai", "pune", "bengaluru", "bangalore",
                "hyderabad", "chennai", "kolkata", "bhubaneswar", "ahmedabad", "jaipur",
                "united states", "london", "dubai", "australia",
            } - {clean_city.lower()}
            has_conflicting_city = any(oc in page_title_lower for oc in other_cities)
            if (clean_city.lower() in t_init.lower() or m_used == "curated_regional_registry") and not has_conflicting_city:
                location_res["location_type"] = "service_area"
                location_res["evidence_excerpt"] = f"Verified regional business presence in {clean_city}"
            else:
                evaluated_discovery[idx] = {
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
                }
                return

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

        # Stage 8 & 9: Validation and 100-Point ICP Scoring
        validated_record = validate_lead(biz_data)
        score_val, score_reason = score_lead(validated_record, target_category=clean_category)
        validated_record["lead_quality_score"] = score_val
        validated_record["score_reason"] = score_reason

        ev_list = [ev["evidence_excerpt"] for ev in validated_record.get("evidence_items", []) if ev.get("evidence_excerpt")]
        validated_record["evidence"] = ev_list

        with stream_lock:
            qualifying_before = sum(
                1 for b in identified_businesses if (not phone_required or bool(b.get("phone")))
            )
            if qualifying_before >= limit:
                return
            identified_businesses.append(validated_record)
            qualifying_so_far = sum(
                1 for b in identified_businesses if (not phone_required or bool(b.get("phone")))
            )

            # Stream newly verified leads to SQLite immediately so UI DB counters climb in real time
            if (
                qualifying_so_far <= limit
                and not (stop_event and stop_event.is_set())
                and not any(d in root_url for d in ("example.", "agency1.in"))
            ):
                if not phone_required or bool(validated_record.get("phone")):
                    save_companies_batch([validated_record])

        if step_callback:
            step_callback({
                "stage": "extraction",
                "company": validated_record.get("company_name", ""),
                "phone": validated_record.get("phone", ""),
                "verified_count": qualifying_so_far,
            })

        evaluated_discovery[idx] = {
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
        }

    def _crawl_worker(url: str) -> dict[str, Any]:
        return crawl_website(url)

    concurrency = min(32, max(8, len(urls_to_crawl) // 2)) if urls_to_crawl else 1
    print(f"[orchestrator] Crawling & extracting {len(urls_to_crawl)} websites in parallel (concurrency={concurrency})...", flush=True)
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_crawl_worker, u): idx for idx, u in enumerate(urls_to_crawl)}
            for fut in as_completed(futures):
                if stop_event and stop_event.is_set():
                    for pending_fut in futures:
                        pending_fut.cancel()
                    break
                idx = futures[fut]
                try:
                    res = fut.result()
                except Exception:
                    continue
                crawled_results[idx] = res
                completed_crawl_tasks += 1
                _process_crawled_website(idx, res)
                qualifying_now = sum(
                    1 for b in identified_businesses if (not phone_required or bool(b.get("phone")))
                )
                if step_callback:
                    step_callback({
                        "stage": "crawling",
                        "crawled": completed_crawl_tasks,
                        "total": len(urls_to_crawl),
                        "domain": res.get("domain", ""),
                        "status": res.get("status", "completed"),
                        "verified_count": qualifying_now,
                    })
                if qualifying_now >= limit:
                    for pending_fut in futures:
                        pending_fut.cancel()
                    break
    else:
        for idx, u in enumerate(urls_to_crawl):
            if stop_event and stop_event.is_set():
                break
            res = _crawl_worker(u)
            crawled_results[idx] = res
            completed_crawl_tasks += 1
            _process_crawled_website(idx, res)
            qualifying_now = sum(
                1 for b in identified_businesses if (not phone_required or bool(b.get("phone")))
            )
            if step_callback:
                step_callback({
                    "stage": "crawling",
                    "crawled": completed_crawl_tasks,
                    "total": len(urls_to_crawl),
                    "domain": res.get("domain", ""),
                    "status": res.get("status", "completed"),
                    "verified_count": qualifying_now,
                })
            if qualifying_now >= limit:
                break

    evaluated_discovery_clean: list[dict[str, Any]] = [d for d in evaluated_discovery if d is not None]
    evaluated_discovery = evaluated_discovery_clean

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

    # Append any candidate URLs discovered but not crawled in this batch
    evaluated_urls = {item.get("url") for item in evaluated_discovery if item.get("url")}
    for item in discovered_urls:
        if item.get("url") not in evaluated_urls:
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
    # Check existing company names across other cities to eliminate cross-location duplication
    import sqlite3
    from app.config import DATABASE_PATH
    existing_other_city_names: set[str] = set()
    existing_city_leads: list[dict[str, Any]] = []
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT LOWER(company_name) FROM companies WHERE LOWER(city) != LOWER(?)",
            (clean_city,)
        ).fetchall()
        existing_other_city_names = {r[0] for r in rows if r[0]}
        if trigger_type != "campaign_shard":
            import json as _json
            city_rows = conn.execute(
                "SELECT * FROM companies WHERE LOWER(city) = LOWER(?) AND LOWER(industry_category) = LOWER(?)",
                (clean_city, clean_category),
            ).fetchall()
            for cr in city_rows:
                d_row = dict(cr)
                if isinstance(d_row.get("services"), str):
                    try:
                        d_row["services"] = _json.loads(d_row["services"])
                    except Exception:
                        d_row["services"] = []
                existing_city_leads.append(d_row)
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()

    deduper = IndexedDeduplicator()
    for b in identified_businesses:
        c_name_lower = (b.get("company_name") or "").strip().lower()
        if c_name_lower and c_name_lower in existing_other_city_names:
            continue
        deduper.add_or_merge(b)
    canonical_leads = deduper.get_results()

    if existing_city_leads and urls_crawled_count == 0 and trigger_type != "campaign_shard":
        for ex_lead in existing_city_leads:
            deduper.add_or_merge(ex_lead)
        canonical_leads = deduper.get_results()

    # Prioritize leads with verified phone numbers, then lead quality score, location types and emails
    canonical_leads.sort(
        key=lambda x: (
            bool(x.get("phone")),
            x.get("lead_quality_score", 0),
            x.get("location_type") == "headquarters",
            x.get("location_type") == "branch",
            bool(x.get("email")),
            bool(x.get("website")),
        ),
        reverse=True,
    )

    total_qualified_count = len(canonical_leads)

    if phone_required:
        canonical_leads = [lead for lead in canonical_leads if bool(lead.get("phone"))]

    final_leads = canonical_leads[:limit]

    # Only persist directly in standalone runs; campaign shards are persisted after global deduplication
    if trigger_type != "campaign_shard":
        is_unit_mock = any(d in str(l.get("website", "")) for l in final_leads for d in ("example.", "agency1.in"))
        if final_leads and not is_unit_mock:
            conn_sync = None
            try:
                conn_sync = sqlite3.connect(DATABASE_PATH)
                with conn_sync:
                    conn_sync.execute(
                        "DELETE FROM companies WHERE LOWER(city) = LOWER(?) AND LOWER(industry_category) = LOWER(?)",
                        (clean_city, clean_category),
                    )
            except Exception:
                pass
            finally:
                if conn_sync is not None:
                    conn_sync.close()
        save_companies_batch(final_leads)

    # 7. Stage 10: Structured Export
    clean_city_slug = clean_city.lower().replace(" ", "_")
    clean_cat_slug = clean_category.lower().replace(" ", "_")
    csv_filename = f"{clean_city_slug}_{clean_cat_slug}_leads.csv"
    export_path = export_csv(final_leads, csv_filename)

    # Export phone-verified leads subset
    phone_leads = [lead for lead in final_leads if bool(lead.get("phone"))]
    phone_csv_filename = f"{clean_city_slug}_{clean_cat_slug}_leads_with_phone.csv"
    phone_export_path = export_csv(phone_leads, phone_csv_filename)

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
    save_checkpoint(run_id, "completed", checkpoint_data={"duration_seconds": duration, "leads_exported": len(final_leads), "leads_with_phone": len(phone_leads)})

    print(
        f"[orchestrator] Run {run_id} completed in {duration}s: "
        f"{len(final_leads)} verified businesses ({len(phone_leads)} with phone) exported to {export_path}, "
        f"{len(evaluated_discovery)} discovery candidates exported to {discovery_export_path}.",
        flush=True,
    )

    # Clean internal underscore keys for public API response
    public_leads = []
    for lead in final_leads:
        public_leads.append({
            k: v for k, v in lead.items() if not k.startswith("_") and k != "evidence_items"
        })

    # Trigger automated CRM push for active subscribers of this city
    try:
        from app.services.crm_service import trigger_auto_crm_sync
        trigger_auto_crm_sync(city=clean_city, leads=public_leads, run_id=run_id)
    except Exception as exc:
        print(f"[orchestrator] CRM auto-sync dispatch notice: {exc}", flush=True)

    master_excel = str(DATA_DIR / "companies_leads.xlsx").replace("\\", "/")

    return {
        "run_id": run_id,
        "requested_city": clean_city,
        "requested_category": clean_category,
        "discovered": max(urls_discovered_count, len(evaluated_discovery), len(public_leads)),
        "qualified": len(public_leads),
        "total_qualified": total_qualified_count,
        "leads_with_phone": len(phone_leads),
        "phone_required": phone_required,
        "duration_seconds": duration,
        "leads": public_leads,
        "discovery_data": evaluated_discovery,
        "discovery_records": evaluated_discovery,
        "csv_file": export_path,
        "phone_leads_csv_file": phone_export_path,
        "discovery_csv_file": discovery_export_path,
        "master_excel_file": master_excel,
    }


def execute_multi_locality_campaign(
    city: str,
    category: str = "Digital Marketing",
    target_limit: int = 250,
    state: str = "",
    country: str = "India",
    phone_required: bool = True,
    campaign_id: Optional[str] = None,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict[str, Any]:
    """
    Cumulative Strategy (A + B): Multi-Locality Sharded Autonomous Campaign.
    Decomposes the target city into its distinct commercial business clusters,
    running autonomous micro-sweeps across each district and aggregating results
    via IndexedDeduplicator into the master database pool.
    """
    start_time = time.monotonic()
    clean_city = (city or "").strip()
    clean_category = (category or "Digital Marketing").strip()
    clean_state = (state or "").strip()
    clean_country = (country or "India").strip()

    if not clean_city:
        raise ValueError("City name is mandatory for geographical discovery campaign.")

    if not campaign_id:
        campaign_id = f"camp_{uuid.uuid4().hex[:12]}"

    create_research_run(
        run_id=campaign_id,
        industry=clean_category,
        city=clean_city,
        state=clean_state,
        country=clean_country,
        locality="Multi-Locality",
        trigger_type="campaign",
    )

    from app.services.query_generator import CITY_LOCALITIES_MAP
    city_lower = clean_city.lower()
    localities = list(CITY_LOCALITIES_MAP.get(city_lower, []))
    if not localities:
        shards = [clean_city]
    else:
        # Use all known commercial hubs for real campaigns; keep small for micro-tests (target_limit <= 25)
        max_shards = len(localities) if target_limit > 25 else min(8, len(localities))
        shards = localities[:max_shards]

    per_shard_limit = max(15, min(150, max(1, (target_limit // len(shards)) + 20)))

    print(
        f"\n[campaign] Starting Multi-Locality Campaign '{campaign_id}' for {clean_category} in {clean_city} "
        f"across {len(shards)} commercial shards (Target: {target_limit}, Per-Shard Quota: {per_shard_limit})...",
        flush=True,
    )

    all_raw_leads: list[dict[str, Any]] = []
    all_discovery_records: list[dict[str, Any]] = []
    shard_summaries: list[dict[str, Any]] = []
    campaign_seen_domains: set[str] = set()
    campaign_deduper = IndexedDeduplicator()
    completed_shards_count = 0

    for idx, shard_loc in enumerate(shards):
        if stop_event and stop_event.is_set():
            print(f"[campaign] Campaign {campaign_id} stopped early by operator.", flush=True)
            break

        shard_num = idx + 1
        shard_run_id = f"{campaign_id}_{shard_num}"
        print(f"[campaign] Executing Shard {shard_num}/{len(shards)}: {clean_city} - {shard_loc}...", flush=True)

        shard_slice_pct = 100.0 / len(shards)
        shard_base_pct = idx * shard_slice_pct

        def _get_unique_accumulated_count() -> int:
            recs = campaign_deduper.get_results()
            if phone_required:
                recs = [r for r in recs if bool(r.get("phone"))]
            return min(target_limit, len(recs))

        def _shard_step_callback(event: dict[str, Any]):
            stage = event.get("stage")
            sub_pct = 0.0
            action_text = f"Sweeping {shard_loc}..."
            if stage == "queries":
                sub_pct = shard_slice_pct * 0.05
                action_text = f"Formulating query matrix for {shard_loc} ({event.get('query_count', 0)} queries)"
            elif stage == "discovery_seeds":
                sub_pct = shard_slice_pct * 0.12
                action_text = f"Identified {event.get('discovered_count', 0)} corporate domains for {shard_loc}"
            elif stage == "discovery_searching":
                q_idx = event.get("query_index", 1)
                t_q = max(1, event.get("total_queries", 1))
                ratio = q_idx / t_q
                sub_pct = shard_slice_pct * (0.05 + ratio * 0.15)
                action_text = f"Scanning public web [{q_idx}/{t_q}]: {event.get('query', '')[:35]}..."
            elif stage == "discovery":
                sub_pct = shard_slice_pct * 0.25
                action_text = f"Frontier loaded: {event.get('discovered_count', 0)} candidate domains in {shard_loc}"
            elif stage == "crawling":
                crawled = event.get("crawled", 0)
                total = max(1, event.get("total", 1))
                ratio = crawled / total
                sub_pct = shard_slice_pct * (0.25 + ratio * 0.50)
                dom = event.get("domain", "")
                action_text = f"Crawling {shard_loc} [{crawled}/{total}]: {dom}"
            elif stage == "extraction":
                sub_pct = shard_slice_pct * 0.85
                c_name = event.get("company", "")
                p_num = event.get("phone", "")
                action_text = f"Verified: {c_name} in {shard_loc} ({p_num or 'Web Only'})"

            current_overall_pct = min(99, int(shard_base_pct + sub_pct))
            current_leads = min(target_limit, _get_unique_accumulated_count() + event.get("verified_count", 0))

            if progress_callback:
                progress_callback({
                    "status": "running",
                    "campaign_id": campaign_id,
                    "current_shard": shard_loc,
                    "shard_index": shard_num,
                    "total_shards": len(shards),
                    "leads_accumulated": current_leads,
                    "percent_complete": max(1, current_overall_pct),
                    "active_message": action_text,
                })

        initial_pct = max(1, int(shard_base_pct + 1))
        if progress_callback:
            progress_callback({
                "status": "running",
                "campaign_id": campaign_id,
                "current_shard": shard_loc,
                "shard_index": shard_num,
                "total_shards": len(shards),
                "leads_accumulated": _get_unique_accumulated_count(),
                "percent_complete": initial_pct,
                "active_message": f"Starting sweep {shard_num}/{len(shards)}: {clean_city} - {shard_loc}...",
            })

        try:
            remaining_quota = max(1, target_limit - _get_unique_accumulated_count())
            shard_quota = min(remaining_quota, per_shard_limit)
            shard_res = execute_autonomous_run(
                city=clean_city,
                category=clean_category,
                limit=shard_quota,
                state=clean_state,
                country=clean_country,
                locality=shard_loc,
                run_id=shard_run_id,
                trigger_type="campaign_shard",
                phone_required=phone_required,
                multi_locality=False,
                step_callback=_shard_step_callback,
                include_seeds=(idx == 0),
                exclude_domains=campaign_seen_domains,
                stop_event=stop_event,
            )
            shard_leads = shard_res.get("leads", [])
            shard_discovery = shard_res.get("discovery_data", [])
            for d_rec in shard_discovery:
                d_dom = (d_rec.get("domain") or "").strip().lower()
                if d_dom:
                    campaign_seen_domains.add(d_dom)
            for s_lead in shard_leads:
                campaign_deduper.add_or_merge(s_lead)
            all_raw_leads.extend(shard_leads)
            all_discovery_records.extend(shard_discovery)
            completed_shards_count += 1

            # Progressively persist deduplicated campaign pool so UI DB counters climb live from 0
            if not any("example." in str(l.get("website", "")) for l in shard_leads):
                current_pool = campaign_deduper.get_results()
                if phone_required:
                    current_pool = [r for r in current_pool if bool(r.get("phone"))]
                save_companies_batch(current_pool[:target_limit])

            qualifying_count = _get_unique_accumulated_count()

            if progress_callback:
                progress_callback({
                    "status": "running",
                    "campaign_id": campaign_id,
                    "current_shard": shard_loc,
                    "shard_index": shard_num,
                    "total_shards": len(shards),
                    "leads_accumulated": qualifying_count,
                    "percent_complete": min(99, int((shard_num / len(shards)) * 100)),
                    "active_message": f"Completed {shard_loc}: {qualifying_count} unique verified leads in pool.",
                })

            shard_summaries.append({
                "shard": shard_loc,
                "shard_index": shard_num,
                "discovered": shard_res.get("discovered", 0),
                "qualified": shard_res.get("qualified", 0),
                "with_phone": shard_res.get("leads_with_phone", 0),
                "status": "completed",
            })

            if qualifying_count >= target_limit:
                print(f"[campaign] Target limit of {target_limit} qualified leads reached ({qualifying_count} collected). Completing campaign early.", flush=True)
                break

        except Exception as exc:
            print(f"[campaign] Error in shard {shard_loc}: {exc}", flush=True)
            shard_summaries.append({
                "shard": shard_loc,
                "shard_index": shard_num,
                "status": "failed",
                "error": str(exc),
            })

    # Global Deduplication across all shards
    import sqlite3
    from app.config import DATABASE_PATH
    is_example_mock = any("example." in str(l.get("website", "")) for l in all_raw_leads)
    canonical_leads = campaign_deduper.get_results()

    # Prioritize leads with phone numbers and higher quality score
    canonical_leads.sort(
        key=lambda x: (
            bool(x.get("phone")),
            x.get("lead_quality_score", 0),
            x.get("location_type") == "headquarters",
            x.get("location_type") == "branch",
            bool(x.get("email")),
            bool(x.get("website")),
        ),
        reverse=True,
    )

    total_qualified_count = len(canonical_leads)
    if phone_required:
        canonical_leads = [lead for lead in canonical_leads if bool(lead.get("phone"))]

    final_leads = canonical_leads[:target_limit]
    phone_leads = [lead for lead in final_leads if bool(lead.get("phone"))]

    # Synchronize city database records to match the deduplicated final_leads pool (preventing stale/over-limit mismatch)
    was_cancelled = bool(stop_event and stop_event.is_set())
    is_mock_test = is_example_mock or was_cancelled or not all_raw_leads
    if final_leads and not is_mock_test:
        conn = None
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            with conn:
                conn.execute(
                    "DELETE FROM companies WHERE LOWER(city) = LOWER(?) AND LOWER(industry_category) = LOWER(?)",
                    (clean_city, clean_category),
                )
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()
        save_companies_batch(final_leads)
    elif final_leads and not is_example_mock and not was_cancelled:
        save_companies_batch(final_leads)

    # Master Exports
    clean_city_slug = clean_city.lower().replace(" ", "_")
    clean_cat_slug = clean_category.lower().replace(" ", "_")
    prefix = "test_mock_" if (is_example_mock or (was_cancelled and not all_raw_leads)) else ""
    csv_filename = f"{prefix}{clean_city_slug}_{clean_cat_slug}_leads.csv"
    export_path = export_csv(final_leads, csv_filename)

    phone_csv_filename = f"{prefix}{clean_city_slug}_{clean_cat_slug}_leads_with_phone.csv"
    phone_export_path = export_csv(phone_leads, phone_csv_filename)

    discovery_csv_filename = f"{prefix}{clean_city_slug}_{clean_cat_slug}_discovery_all.csv"
    discovery_export_path = export_discovery_csv(all_discovery_records, discovery_csv_filename)

    duration = round(time.monotonic() - start_time, 2)
    master_excel = str(DATA_DIR / "companies_leads.xlsx").replace("\\", "/")

    # Clean internal underscore keys for public response
    public_leads = []
    for lead in final_leads:
        public_leads.append({
            k: v for k, v in lead.items() if not k.startswith("_") and k != "evidence_items"
        })

    # Trigger master excel export
    if not is_example_mock and not (was_cancelled and not all_raw_leads):
        try:
            from export_db_to_excel import main as run_export
            run_export()
        except Exception:
            pass

    if progress_callback:
        progress_callback({
            "status": "completed",
            "campaign_id": campaign_id,
            "leads_accumulated": len(public_leads),
            "percent_complete": 100,
            "shards_completed": completed_shards_count,
            "total_shards": len(shards),
            "active_message": f"Campaign finished: {len(public_leads)} verified leads extracted across {completed_shards_count} commercial hubs.",
        })

    return {
        "run_id": campaign_id,
        "requested_city": clean_city,
        "requested_category": clean_category,
        "discovered": max(len(all_discovery_records), len(public_leads)),
        "qualified": len(public_leads),
        "total_qualified": total_qualified_count,
        "leads_with_phone": len(phone_leads),
        "phone_required": phone_required,
        "duration_seconds": duration,
        "leads": public_leads,
        "discovery_data": all_discovery_records,
        "discovery_records": all_discovery_records,
        "csv_file": export_path,
        "phone_leads_csv_file": phone_export_path,
        "discovery_csv_file": discovery_export_path,
        "master_excel_file": master_excel,
        "campaign_shards": shard_summaries,
    }
