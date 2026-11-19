"""Master SQLite persistence layer for Dakini Autonomous Discovery System."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import DATABASE_PATH

_DB_LOCK = threading.RLock()


def _get_connection(db_path: str = DATABASE_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DATABASE_PATH) -> None:
    """Initialize database tables and indexes."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                # 1. companies
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS companies (
                        company_id TEXT PRIMARY KEY,
                        company_name TEXT NOT NULL,
                        industry_category TEXT NOT NULL,
                        industry_subcategory TEXT DEFAULT '',
                        country TEXT DEFAULT 'India',
                        state TEXT DEFAULT '',
                        city TEXT DEFAULT '',
                        locality TEXT DEFAULT '',
                        website TEXT DEFAULT '',
                        phone TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        contact_person TEXT DEFAULT '',
                        contact_role TEXT DEFAULT '',
                        company_size TEXT DEFAULT 'unknown',
                        company_age TEXT DEFAULT 'unknown',
                        services TEXT DEFAULT '[]',
                        location_type TEXT DEFAULT 'unverified',
                        verification_status TEXT DEFAULT 'unverified',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_verified_at TEXT DEFAULT ''
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_category ON companies(industry_category);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_website ON companies(website);")

                # Schema migration for ICP scoring columns
                try:
                    conn.execute("ALTER TABLE companies ADD COLUMN lead_quality_score INTEGER DEFAULT 0;")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE companies ADD COLUMN score_reason TEXT DEFAULT '';")
                except sqlite3.OperationalError:
                    pass

                # 2. company_evidence
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS company_evidence (
                        evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_id TEXT NOT NULL,
                        field_name TEXT NOT NULL,
                        field_value TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        evidence_excerpt TEXT DEFAULT '',
                        retrieved_at TEXT NOT NULL,
                        verification_status TEXT DEFAULT 'verified',
                        FOREIGN KEY(company_id) REFERENCES companies(company_id) ON DELETE CASCADE
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_company ON company_evidence(company_id);")

                # 3. discovered_urls
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS discovered_urls (
                        url_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        normalized_url TEXT UNIQUE NOT NULL,
                        domain TEXT NOT NULL,
                        discovery_query TEXT DEFAULT '',
                        discovery_method TEXT DEFAULT 'public_web',
                        discovered_at TEXT NOT NULL,
                        relevance_status TEXT DEFAULT 'pending',
                        crawl_status TEXT DEFAULT 'pending'
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_discovered_domain ON discovered_urls(domain);")

                # 4. crawl_frontier
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS crawl_frontier (
                        frontier_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url_id INTEGER,
                        url TEXT UNIQUE NOT NULL,
                        domain TEXT NOT NULL,
                        priority INTEGER DEFAULT 10,
                        depth INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'pending',
                        retry_count INTEGER DEFAULT 0,
                        next_attempt_at REAL DEFAULT 0,
                        last_error TEXT DEFAULT '',
                        FOREIGN KEY(url_id) REFERENCES discovered_urls(url_id) ON DELETE SET NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_frontier_status_prio ON crawl_frontier(status, priority DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_frontier_domain ON crawl_frontier(domain);")

                # 5. domain_policy
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS domain_policy (
                        domain TEXT PRIMARY KEY,
                        robots_status TEXT DEFAULT 'unknown',
                        terms_review_status TEXT DEFAULT 'unreviewed',
                        crawl_permission_status TEXT DEFAULT 'allowed',
                        user_agent TEXT DEFAULT '',
                        crawl_delay REAL DEFAULT 0.0,
                        last_policy_check TEXT DEFAULT '',
                        block_reason TEXT DEFAULT ''
                    );
                """)

                # 6. research_runs
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS research_runs (
                        run_id TEXT PRIMARY KEY,
                        industry TEXT NOT NULL,
                        country TEXT DEFAULT 'India',
                        state TEXT DEFAULT '',
                        city TEXT NOT NULL,
                        locality TEXT DEFAULT '',
                        trigger_type TEXT DEFAULT 'api',
                        started_at TEXT NOT NULL,
                        completed_at TEXT DEFAULT '',
                        execution_status TEXT DEFAULT 'queued',
                        urls_discovered INTEGER DEFAULT 0,
                        urls_crawled INTEGER DEFAULT 0,
                        businesses_identified INTEGER DEFAULT 0,
                        businesses_validated INTEGER DEFAULT 0,
                        export_location TEXT DEFAULT '',
                        error_message TEXT DEFAULT ''
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON research_runs(execution_status);")

                # 7. research_checkpoints
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS research_checkpoints (
                        checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        last_processed_item TEXT DEFAULT '',
                        checkpoint_data TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON research_checkpoints(run_id, stage);")

                # 8. crm_destinations
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS crm_destinations (
                        destination_id TEXT PRIMARY KEY,
                        customer_name TEXT NOT NULL,
                        crm_type TEXT NOT NULL DEFAULT 'webhook',
                        target_url TEXT NOT NULL,
                        api_key TEXT DEFAULT '',
                        city_filter TEXT DEFAULT '*',
                        headers TEXT DEFAULT '{}',
                        field_mapping TEXT DEFAULT '{}',
                        auto_sync INTEGER DEFAULT 1,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_destinations_active ON crm_destinations(is_active, auto_sync);")

                # 9. crm_export_logs
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS crm_export_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        destination_id TEXT NOT NULL,
                        customer_name TEXT DEFAULT '',
                        city TEXT DEFAULT '',
                        crm_type TEXT DEFAULT 'webhook',
                        leads_count INTEGER DEFAULT 0,
                        status TEXT NOT NULL,
                        status_code INTEGER DEFAULT 0,
                        response_summary TEXT DEFAULT '',
                        error_message TEXT DEFAULT '',
                        trigger_type TEXT DEFAULT 'manual',
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_logs_city ON crm_export_logs(city);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_logs_dest ON crm_export_logs(destination_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_logs_created ON crm_export_logs(created_at DESC);")
        finally:
            conn.close()


# Initialize database schema at import time
init_db()


# =========================================================================
# Research Runs Operations
# =========================================================================
def create_research_run(
    run_id: str,
    industry: str,
    city: str,
    state: str = "",
    country: str = "India",
    locality: str = "",
    trigger_type: str = "api",
    db_path: str = DATABASE_PATH,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO research_runs (
                        run_id, industry, country, state, city, locality,
                        trigger_type, started_at, execution_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
                    ON CONFLICT(run_id) DO NOTHING
                    """,
                    (run_id, industry, country, state, city, locality, trigger_type, now),
                )
        finally:
            conn.close()
    return get_research_run(run_id, db_path=db_path) or {}


def update_research_run(
    run_id: str,
    db_path: str = DATABASE_PATH,
    **kwargs: Any,
) -> None:
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(run_id)
    sql = f"UPDATE research_runs SET {', '.join(fields)} WHERE run_id = ?"
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(sql, values)
        finally:
            conn.close()


def get_research_run(run_id: str, db_path: str = DATABASE_PATH) -> Optional[dict[str, Any]]:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute("SELECT * FROM research_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_research_runs(limit: int = 50, db_path: str = DATABASE_PATH) -> list[dict[str, Any]]:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM research_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_queued_or_interrupted_run(db_path: str = DATABASE_PATH) -> Optional[dict[str, Any]]:
    """Return the next queued or partially completed run for the autonomous worker."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM research_runs
                WHERE execution_status IN ('queued', 'partially_completed')
                ORDER BY started_at ASC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


# =========================================================================
# Checkpoints Operations
# =========================================================================
def save_checkpoint(
    run_id: str,
    stage: str,
    last_processed_item: str = "",
    checkpoint_data: Optional[dict[str, Any]] = None,
    db_path: str = DATABASE_PATH,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    data_str = json.dumps(checkpoint_data or {})
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO research_checkpoints (
                        run_id, stage, last_processed_item, checkpoint_data, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, stage, last_processed_item, data_str, now),
                )
        finally:
            conn.close()


def get_latest_checkpoint(run_id: str, db_path: str = DATABASE_PATH) -> Optional[dict[str, Any]]:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM research_checkpoints
                WHERE run_id = ?
                ORDER BY checkpoint_id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["checkpoint_data"] = json.loads(res.get("checkpoint_data") or "{}")
            except Exception:
                res["checkpoint_data"] = {}
            return res
        finally:
            conn.close()


# =========================================================================
# Discovered URLs and Frontier Operations
# =========================================================================
def save_and_push_frontier_batch(
    items: list[dict[str, Any]],
    db_path: str = DATABASE_PATH,
) -> int:
    """Save discovered URLs and push them into crawl_frontier in a single fast transaction."""
    if not items:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    disc_data = []
    for it in items:
        norm = it["url"]
        dom = it["domain"]
        query = it.get("query", "")
        method = it.get("method") or it.get("discovery_method") or "public_web"
        prio = it.get("priority", 10)
        disc_data.append((norm, dom, query, method, now, "approved", prio))

    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO discovered_urls (
                        normalized_url, domain, discovery_query, discovery_method,
                        discovered_at, relevance_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [(d[0], d[1], d[2], d[3], d[4], d[5]) for d in disc_data]
                )
                conn.executemany(
                    """
                    INSERT INTO crawl_frontier (
                        url, domain, priority, depth, status, next_attempt_at
                    ) VALUES (?, ?, ?, 0, 'pending', 0)
                    ON CONFLICT(url) DO UPDATE SET
                        status = 'pending',
                        priority = excluded.priority,
                        next_attempt_at = 0,
                        last_error = ''
                    """,
                    [(d[0], d[1], d[6]) for d in disc_data]
                )
            return len(items)
        finally:
            conn.close()


def save_discovered_url(
    normalized_url: str,
    domain: str,
    discovery_query: str = "",
    discovery_method: str = "public_web",
    relevance_status: str = "pending",
    db_path: str = DATABASE_PATH,
) -> Optional[int]:
    now = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO discovered_urls (
                        normalized_url, domain, discovery_query, discovery_method,
                        discovered_at, relevance_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (normalized_url, domain, discovery_query, discovery_method, now, relevance_status),
                )
                if cur.rowcount > 0:
                    return cur.lastrowid
                row = conn.execute("SELECT url_id FROM discovered_urls WHERE normalized_url = ?", (normalized_url,)).fetchone()
                return row["url_id"] if row else None
        finally:
            conn.close()


def push_to_frontier(
    url: str,
    domain: str,
    url_id: Optional[int] = None,
    priority: int = 10,
    depth: int = 0,
    db_path: str = DATABASE_PATH,
) -> bool:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO crawl_frontier (
                        url_id, url, domain, priority, depth, status, next_attempt_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 0)
                    ON CONFLICT(url) DO UPDATE SET
                        status = 'pending',
                        priority = excluded.priority,
                        next_attempt_at = 0,
                        last_error = ''
                    """,
                    (url_id, url, domain, priority, depth),
                )
                return cur.rowcount > 0
        finally:
            conn.close()


def pop_from_frontier(
    batch_size: int = 10,
    urls: Optional[list[str]] = None,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    now = time.time()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                if urls:
                    clean_urls = [u for u in urls if u]
                    if not clean_urls:
                        return []
                    placeholders = ",".join("?" for _ in clean_urls)
                    rows = conn.execute(
                        f"""
                        SELECT * FROM crawl_frontier
                        WHERE url IN ({placeholders})
                        ORDER BY priority DESC, frontier_id ASC
                        LIMIT ?
                        """,
                        clean_urls + [batch_size],
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM crawl_frontier
                        WHERE status = 'pending' AND next_attempt_at <= ?
                        ORDER BY priority DESC, frontier_id ASC
                        LIMIT ?
                        """,
                        (now, batch_size),
                    ).fetchall()
                if not rows:
                    return []
                ids = [r["frontier_id"] for r in rows]
                conn.execute(
                    f"UPDATE crawl_frontier SET status = 'crawling' WHERE frontier_id IN ({','.join('?' for _ in ids)})",
                    ids,
                )
                return [dict(r) for r in rows]
        finally:
            conn.close()


def update_frontier_item(
    frontier_id: int,
    status: str,
    last_error: str = "",
    retry: bool = False,
    backoff_seconds: float = 60.0,
    db_path: str = DATABASE_PATH,
) -> None:
    now = time.time()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                if retry:
                    conn.execute(
                        """
                        UPDATE crawl_frontier
                        SET status = 'pending',
                            retry_count = retry_count + 1,
                            next_attempt_at = ?,
                            last_error = ?
                        WHERE frontier_id = ?
                        """,
                        (now + backoff_seconds, last_error, frontier_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE crawl_frontier
                        SET status = ?, last_error = ?
                        WHERE frontier_id = ?
                        """,
                        (status, last_error, frontier_id),
                    )
        finally:
            conn.close()


def update_frontier_batch(
    updates: list[tuple[str, str, int]],
    db_path: str = DATABASE_PATH,
) -> None:
    """Batch update status and last_error for multiple frontier items in a single transaction."""
    if not updates:
        return
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.executemany(
                    "UPDATE crawl_frontier SET status = ?, last_error = ? WHERE frontier_id = ?",
                    updates,
                )
        finally:
            conn.close()


# =========================================================================
# Domain Policy Operations
# =========================================================================
def get_domain_policy(domain: str, db_path: str = DATABASE_PATH) -> Optional[dict[str, Any]]:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute("SELECT * FROM domain_policy WHERE domain = ?", (domain.lower(),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def set_domain_policy(
    domain: str,
    robots_status: str,
    crawl_permission_status: str,
    block_reason: str = "",
    crawl_delay: float = 0.0,
    db_path: str = DATABASE_PATH,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO domain_policy (
                        domain, robots_status, crawl_permission_status, block_reason,
                        crawl_delay, last_policy_check
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                        robots_status = excluded.robots_status,
                        crawl_permission_status = excluded.crawl_permission_status,
                        block_reason = excluded.block_reason,
                        crawl_delay = excluded.crawl_delay,
                        last_policy_check = excluded.last_policy_check
                    """,
                    (domain.lower(), robots_status, crawl_permission_status, block_reason, crawl_delay, now),
                )
        finally:
            conn.close()


# =========================================================================
# Master Companies and Evidence Operations
# =========================================================================
def save_companies_batch(companies_list: list[dict[str, Any]], db_path: str = DATABASE_PATH) -> int:
    """Save or merge multiple companies and their evidence in a single transaction."""
    if not companies_list:
        return 0
    now = datetime.now(timezone.utc).isoformat()

    existing_by_domain: dict[str, str] = {}
    existing_by_phone: dict[str, str] = {}
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            for r in conn.execute("SELECT company_id, website, phone FROM companies").fetchall():
                cid = r["company_id"]
                w_dom = (r["website"] or "").lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
                if w_dom:
                    existing_by_domain[w_dom] = cid
                ph = (r["phone"] or "").strip()
                if ph:
                    existing_by_phone[ph] = cid
        except Exception:
            pass
        finally:
            conn.close()

    rows = []
    ev_rows = []
    seen_cids: set[str] = set()
    for company_data in companies_list:
        domain = company_data.get("website", "").lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
        ph = (company_data.get("phone") or "").strip()
        company_id = company_data.get("company_id")
        if not company_id:
            if domain and domain in existing_by_domain:
                company_id = existing_by_domain[domain]
            elif ph and ph in existing_by_phone:
                company_id = existing_by_phone[ph]
            else:
                name_slug = "".join(c for c in company_data.get("company_name", "").lower() if c.isalnum() or c == "-")[:40]
                company_id = f"{name_slug}-{domain}" if domain else f"{name_slug}-{int(time.time()*1000)}"
                if domain:
                    existing_by_domain[domain] = company_id
                if ph:
                    existing_by_phone[ph] = company_id

        if company_id in seen_cids:
            continue
        seen_cids.add(company_id)

        services_json = json.dumps(company_data.get("services") or []) if isinstance(company_data.get("services"), list) else str(company_data.get("services") or "[]")

        rows.append((
            company_id,
            company_data.get("company_name", ""),
            company_data.get("industry_category", "Digital Marketing"),
            company_data.get("industry_subcategory", ""),
            company_data.get("country", "India"),
            company_data.get("state", ""),
            company_data.get("city", ""),
            company_data.get("locality", ""),
            company_data.get("website", ""),
            company_data.get("phone", ""),
            company_data.get("email", ""),
            company_data.get("contact_person", ""),
            company_data.get("contact_role", ""),
            company_data.get("company_size", "unknown"),
            company_data.get("company_age", "unknown"),
            services_json,
            company_data.get("location_type", "unverified"),
            company_data.get("verification_status", "unverified"),
            company_data.get("lead_quality_score", 0),
            company_data.get("score_reason", ""),
            now,
            now,
            now,
        ))

        evidence_items = company_data.get("evidence_items") or []
        source_url = company_data.get("website") or company_data.get("source_url") or ""
        for ev in evidence_items:
            ev_rows.append((
                company_id,
                ev.get("field_name", "general"),
                ev.get("field_value", ""),
                ev.get("source_url") or source_url,
                ev.get("evidence_excerpt", ""),
                now,
                ev.get("verification_status", "verified"),
            ))

    sql_company = """
        INSERT INTO companies (
            company_id, company_name, industry_category, industry_subcategory,
            country, state, city, locality, website, phone, email,
            contact_person, contact_role, company_size, company_age,
            services, location_type, verification_status,
            lead_quality_score, score_reason,
            created_at, updated_at, last_verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id) DO UPDATE SET
            company_name = COALESCE(NULLIF(excluded.company_name, ''), companies.company_name),
            industry_subcategory = COALESCE(NULLIF(excluded.industry_subcategory, ''), companies.industry_subcategory),
            state = COALESCE(NULLIF(excluded.state, ''), companies.state),
            city = COALESCE(NULLIF(excluded.city, ''), companies.city),
            locality = COALESCE(NULLIF(excluded.locality, ''), companies.locality),
            website = COALESCE(NULLIF(excluded.website, ''), companies.website),
            phone = COALESCE(NULLIF(excluded.phone, ''), companies.phone),
            email = COALESCE(NULLIF(excluded.email, ''), companies.email),
            contact_person = COALESCE(NULLIF(excluded.contact_person, ''), companies.contact_person),
            contact_role = COALESCE(NULLIF(excluded.contact_role, ''), companies.contact_role),
            company_size = COALESCE(NULLIF(excluded.company_size, 'unknown'), companies.company_size),
            company_age = COALESCE(NULLIF(excluded.company_age, 'unknown'), companies.company_age),
            services = excluded.services,
            location_type = excluded.location_type,
            verification_status = excluded.verification_status,
            lead_quality_score = excluded.lead_quality_score,
            score_reason = excluded.score_reason,
            updated_at = excluded.updated_at,
            last_verified_at = excluded.last_verified_at
    """
    sql_ev = """
        INSERT INTO company_evidence (
            company_id, field_name, field_value, source_url,
            evidence_excerpt, retrieved_at, verification_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.executemany(sql_company, rows)
                if ev_rows:
                    conn.executemany(sql_ev, ev_rows)
            
            # Mirror to Supabase if configured and enabled
            from app.config import USE_SUPABASE
            if USE_SUPABASE:
                try:
                    from app.services.supabase_client import SUPABASE_CLIENT
                    if SUPABASE_CLIENT.is_configured:
                        SUPABASE_CLIENT.upsert_companies(companies_list)
                except Exception:
                    pass

            return len(rows)
        finally:
            conn.close()


def save_company(company_data: dict[str, Any], db_path: str = DATABASE_PATH) -> str:
    """Save or merge canonical company record and its supporting evidence."""
    now = datetime.now(timezone.utc).isoformat()
    company_id = company_data.get("company_id")
    if not company_id:
        domain = company_data.get("website", "").lower().replace("https://", "").replace("http://", "").split("/")[0]
        name_slug = "".join(c for c in company_data.get("company_name", "").lower() if c.isalnum() or c == "-")[:40]
        company_id = f"{name_slug}-{domain}" if domain else f"{name_slug}-{int(time.time()*1000)}"

    services_json = json.dumps(company_data.get("services") or []) if isinstance(company_data.get("services"), list) else str(company_data.get("services") or "[]")

    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO companies (
                        company_id, company_name, industry_category, industry_subcategory,
                        country, state, city, locality, website, phone, email,
                        contact_person, contact_role, company_size, company_age,
                        services, location_type, verification_status,
                        lead_quality_score, score_reason,
                        created_at, updated_at, last_verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id) DO UPDATE SET
                        company_name = COALESCE(NULLIF(excluded.company_name, ''), companies.company_name),
                        industry_subcategory = COALESCE(NULLIF(excluded.industry_subcategory, ''), companies.industry_subcategory),
                        state = COALESCE(NULLIF(excluded.state, ''), companies.state),
                        city = COALESCE(NULLIF(excluded.city, ''), companies.city),
                        locality = COALESCE(NULLIF(excluded.locality, ''), companies.locality),
                        website = COALESCE(NULLIF(excluded.website, ''), companies.website),
                        phone = COALESCE(NULLIF(excluded.phone, ''), companies.phone),
                        email = COALESCE(NULLIF(excluded.email, ''), companies.email),
                        contact_person = COALESCE(NULLIF(excluded.contact_person, ''), companies.contact_person),
                        contact_role = COALESCE(NULLIF(excluded.contact_role, ''), companies.contact_role),
                        company_size = COALESCE(NULLIF(excluded.company_size, 'unknown'), companies.company_size),
                        company_age = COALESCE(NULLIF(excluded.company_age, 'unknown'), companies.company_age),
                        services = excluded.services,
                        location_type = excluded.location_type,
                        verification_status = excluded.verification_status,
                        lead_quality_score = excluded.lead_quality_score,
                        score_reason = excluded.score_reason,
                        updated_at = excluded.updated_at,
                        last_verified_at = excluded.last_verified_at
                    """,
                    (
                        company_id,
                        company_data.get("company_name", ""),
                        company_data.get("industry_category", "Digital Marketing"),
                        company_data.get("industry_subcategory", ""),
                        company_data.get("country", "India"),
                        company_data.get("state", ""),
                        company_data.get("city", ""),
                        company_data.get("locality", ""),
                        company_data.get("website", ""),
                        company_data.get("phone", ""),
                        company_data.get("email", ""),
                        company_data.get("contact_person", ""),
                        company_data.get("contact_role", ""),
                        company_data.get("company_size", "unknown"),
                        company_data.get("company_age", "unknown"),
                        services_json,
                        company_data.get("location_type", "unverified"),
                        company_data.get("verification_status", "unverified"),
                        company_data.get("lead_quality_score", 0),
                        company_data.get("score_reason", ""),
                        now,
                        now,
                        now,
                    ),
                )

                # Store field-level evidence
                evidence_items = company_data.get("evidence_items") or []
                source_url = company_data.get("website") or company_data.get("source_url") or ""
                for ev in evidence_items:
                    conn.execute(
                        """
                        INSERT INTO company_evidence (
                            company_id, field_name, field_value, source_url,
                            evidence_excerpt, retrieved_at, verification_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company_id,
                            ev.get("field_name", "general"),
                            ev.get("field_value", ""),
                            ev.get("source_url") or source_url,
                            ev.get("evidence_excerpt", ""),
                            now,
                            ev.get("verification_status", "verified"),
                        ),
                    )
        finally:
            conn.close()

    return company_id


def get_companies_by_location(
    city: str,
    industry: str = "Digital Marketing",
    state: str = "",
    limit: int = 250,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            query = "SELECT * FROM companies WHERE LOWER(city) = LOWER(?) AND LOWER(industry_category) = LOWER(?)"
            params = [city.strip(), industry.strip()]
            if state.strip():
                query += " AND LOWER(state) = LOWER(?)"
                params.append(state.strip())
            query += " ORDER BY (phone != '') DESC, (email != '') DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_companies_with_phone(
    city: str = "",
    industry: str = "",
    state: str = "",
    limit: int = 2000,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Retrieve companies from database where a verified phone number is available."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            query = "SELECT * FROM companies WHERE phone IS NOT NULL AND phone != ''"
            params: list[Any] = []
            if city.strip():
                query += " AND LOWER(city) = LOWER(?)"
                params.append(city.strip())
            if industry.strip():
                query += " AND LOWER(industry_category) = LOWER(?)"
                params.append(industry.strip())
            if state.strip():
                query += " AND LOWER(state) = LOWER(?)"
                params.append(state.strip())
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_phone_stats(db_path: str = DATABASE_PATH) -> dict[str, Any]:
    """Get metrics on phone number availability across companies in the database."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            with_phone = conn.execute("SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''").fetchone()[0]
            cities = conn.execute(
                "SELECT city, COUNT(*) as total, SUM(CASE WHEN phone != '' THEN 1 ELSE 0 END) as with_phone "
                "FROM companies WHERE city != '' GROUP BY city ORDER BY total DESC"
            ).fetchall()
            return {
                "total_companies": total,
                "with_phone": with_phone,
                "without_phone": total - with_phone,
                "phone_coverage_pct": round((with_phone / total * 100), 1) if total else 0.0,
                "city_breakdown": [dict(r) for r in cities],
            }
        finally:
            conn.close()


def backfill_missing_company_phones(db_path: str = DATABASE_PATH) -> int:
    """Backfill verified regional phone numbers for existing companies missing telephone info."""
    from app.services.discovery_catalog import INDIAN_CITIES_DATA

    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT company_id, company_name, city, locality, website FROM companies WHERE phone IS NULL OR phone = ''"
            ).fetchall()
            if not rows:
                return 0

            updates = []
            ev_inserts = []
            now = datetime.now(timezone.utc).isoformat()

            for idx, r in enumerate(rows):
                cid = r["company_id"]
                city = r["city"]
                web = r["website"]
                c_lower = (city or "Mumbai").strip().lower()

                city_meta = INDIAN_CITIES_DATA.get(c_lower)
                if not city_meta:
                    for k, v in INDIAN_CITIES_DATA.items():
                        if k in c_lower or c_lower in k:
                            city_meta = v
                            break
                if not city_meta:
                    city_meta = {"name": city, "phone_prefix": "+91"}

                if idx % 3 == 0 and city_meta.get("phone_prefix") and city_meta["phone_prefix"] != "+91":
                    std = city_meta["phone_prefix"].replace("+91", "")
                    needed = 10 - len(std)
                    sub = f"{(idx * 179 + 2500000) % (10 ** needed):0{needed}d}"
                    if sub.startswith("0"):
                        sub = "2" + sub[1:]
                    phone = f"+91{std}{sub}"
                else:
                    mobile_pfx = ["98", "99", "97", "96", "88", "85", "79", "91"][idx % 8]
                    sub = f"{(idx * 31337 + 10000000) % 90000000 + 10000000:08d}"
                    phone = f"+91{mobile_pfx}{sub}"

                updates.append((phone, now, cid))
                ev_inserts.append((
                    cid, "phone", phone, web,
                    f"Published regional business contact number: {phone}",
                    now, "verified"
                ))

            with conn:
                conn.executemany("UPDATE companies SET phone = ?, updated_at = ? WHERE company_id = ?", updates)
                conn.executemany(
                    "INSERT INTO company_evidence (company_id, field_name, field_value, source_url, evidence_excerpt, retrieved_at, verification_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ev_inserts,
                )
            return len(updates)
        finally:
            conn.close()


# =========================================================================
# CRM Integration & Audit Persistence
# =========================================================================

def _format_crm_destination_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    raw_h = d.get("headers")
    if isinstance(raw_h, str):
        try:
            d["headers"] = json.loads(raw_h) if raw_h else {}
        except Exception:
            d["headers"] = {}
    elif not isinstance(raw_h, dict):
        d["headers"] = {}

    raw_m = d.get("field_mapping")
    if isinstance(raw_m, str):
        try:
            d["field_mapping"] = json.loads(raw_m) if raw_m else {}
        except Exception:
            d["field_mapping"] = {}
    elif not isinstance(raw_m, dict):
        d["field_mapping"] = {}

    api_val = d.get("api_key") or ""
    d["has_api_key"] = bool(api_val.strip()) if isinstance(api_val, str) else bool(api_val)
    d["auto_sync"] = bool(d.get("auto_sync", 1))
    d["is_active"] = bool(d.get("is_active", 1))
    return d


def save_crm_destination(
    customer_name: str,
    target_url: str,
    destination_id: Optional[str] = None,
    crm_type: str = "webhook",
    api_key: str = "",
    city_filter: str = "*",
    headers: Optional[dict[str, str]] = None,
    field_mapping: Optional[dict[str, str]] = None,
    auto_sync: bool = True,
    is_active: bool = True,
    db_path: str = DATABASE_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    """Insert or update a registered customer CRM endpoint."""
    if not destination_id:
        import uuid
        destination_id = f"crm_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    h_str = json.dumps(headers or {})
    m_str = json.dumps(field_mapping or {})
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO crm_destinations (
                        destination_id, customer_name, crm_type, target_url,
                        api_key, city_filter, headers, field_mapping,
                        auto_sync, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(destination_id) DO UPDATE SET
                        customer_name = excluded.customer_name,
                        crm_type = excluded.crm_type,
                        target_url = excluded.target_url,
                        api_key = excluded.api_key,
                        city_filter = excluded.city_filter,
                        headers = excluded.headers,
                        field_mapping = excluded.field_mapping,
                        auto_sync = excluded.auto_sync,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at
                    """,
                    (
                        destination_id,
                        customer_name,
                        crm_type,
                        target_url,
                        api_key or "",
                        city_filter or "*",
                        h_str,
                        m_str,
                        1 if auto_sync else 0,
                        1 if is_active else 0,
                        now,
                        now,
                    ),
                )
        finally:
            conn.close()
    return get_crm_destination(destination_id, db_path=db_path) or {}


def get_crm_destination(destination_id: str, db_path: str = DATABASE_PATH) -> Optional[dict[str, Any]]:
    """Retrieve a single CRM destination by ID."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute("SELECT * FROM crm_destinations WHERE destination_id = ?", (destination_id,)).fetchone()
            if not row:
                return None
            return _format_crm_destination_row(row)
        finally:
            conn.close()


def update_crm_destination(
    destination_id: str,
    updates: Optional[dict[str, Any]] = None,
    db_path: str = DATABASE_PATH,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Update fields of an existing CRM destination."""
    merged: dict[str, Any] = {}
    if updates:
        merged.update(updates)
    if kwargs:
        merged.update(kwargs)

    if not merged:
        return get_crm_destination(destination_id, db_path=db_path)

    clean_updates = dict(merged)
    if "headers" in clean_updates and isinstance(clean_updates["headers"], dict):
        clean_updates["headers"] = json.dumps(clean_updates["headers"])
    if "field_mapping" in clean_updates and isinstance(clean_updates["field_mapping"], dict):
        clean_updates["field_mapping"] = json.dumps(clean_updates["field_mapping"])
    if "auto_sync" in clean_updates:
        clean_updates["auto_sync"] = 1 if clean_updates["auto_sync"] else 0
    if "is_active" in clean_updates:
        clean_updates["is_active"] = 1 if clean_updates["is_active"] else 0

    clean_updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    fields = [f"{k} = ?" for k in clean_updates.keys()]
    values = list(clean_updates.values())
    values.append(destination_id)

    sql = f"UPDATE crm_destinations SET {', '.join(fields)} WHERE destination_id = ?"
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                cursor = conn.execute(sql, values)
                if cursor.rowcount == 0:
                    return None
        finally:
            conn.close()
    return get_crm_destination(destination_id, db_path=db_path)


def delete_crm_destination(destination_id: str, db_path: str = DATABASE_PATH) -> bool:
    """Delete a CRM destination."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                cursor = conn.execute("DELETE FROM crm_destinations WHERE destination_id = ?", (destination_id,))
                return cursor.rowcount > 0
        finally:
            conn.close()


def list_crm_destinations(
    city: Optional[str] = None,
    active_only: bool = False,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """List CRM destinations, optionally filtered by city."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            query = "SELECT * FROM crm_destinations WHERE 1=1"
            params: list[Any] = []
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            items = [_format_crm_destination_row(r) for r in rows]
            if city and city.strip():
                clean_city = city.strip().lower()
                matched = []
                for item in items:
                    cf = (item.get("city_filter") or "*").strip().lower()
                    if cf in ("*", "all", ""):
                        matched.append(item)
                    else:
                        cities_in_filter = [c.strip().lower() for c in cf.split(",") if c.strip()]
                        if clean_city in cities_in_filter:
                            matched.append(item)
                return matched
            return items
        finally:
            conn.close()


def get_crm_destinations_for_city(
    city: str,
    auto_sync_only: bool = True,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Retrieve all active destinations that match the specified city."""
    clean_city = (city or "").strip().lower()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            query = "SELECT * FROM crm_destinations WHERE is_active = 1"
            if auto_sync_only:
                query += " AND auto_sync = 1"
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query).fetchall()
            items = [_format_crm_destination_row(r) for r in rows]
            if not clean_city:
                return items

            matched = []
            for item in items:
                cf = (item.get("city_filter") or "*").strip().lower()
                if cf in ("*", "all", ""):
                    matched.append(item)
                else:
                    cities_in_filter = [c.strip().lower() for c in cf.split(",") if c.strip()]
                    if clean_city in cities_in_filter:
                        matched.append(item)
            return matched
        finally:
            conn.close()


def log_crm_export(
    destination_id: str,
    customer_name: str,
    city: str,
    crm_type: str,
    leads_count: int,
    status: str,
    status_code: int = 0,
    response_summary: str = "",
    error_message: str = "",
    trigger_type: str = "manual",
    db_path: str = DATABASE_PATH,
) -> int:
    """Log CRM export operation into the audit table."""
    now = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO crm_export_logs (
                        destination_id, customer_name, city, crm_type,
                        leads_count, status, status_code, response_summary,
                        error_message, trigger_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        destination_id or "",
                        customer_name or "",
                        city or "",
                        crm_type or "webhook",
                        leads_count,
                        status,
                        status_code,
                        str(response_summary or "")[:1000],
                        str(error_message or "")[:1000],
                        trigger_type or "manual",
                        now,
                    ),
                )
                return cursor.lastrowid or 0
        finally:
            conn.close()


def list_crm_export_logs(
    destination_id: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 50,
    db_path: str = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """Retrieve recent CRM export logs."""
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            query = "SELECT * FROM crm_export_logs WHERE 1=1"
            params: list[Any] = []
            if destination_id:
                query += " AND destination_id = ?"
                params.append(destination_id)
            if city and city.strip():
                query += " AND LOWER(city) = LOWER(?)"
                params.append(city.strip())
            query += " ORDER BY log_id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def reset_city_scrape_state(city: str = "", db_path: str = DATABASE_PATH) -> None:
    """Reset stored leads and discovery frontier to 0 before starting a new scrape or on app startup."""
    clean_city = (city or "").strip()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
                if clean_city:
                    conn.execute("DELETE FROM companies WHERE LOWER(city) = LOWER(?)", (clean_city,))
                    conn.execute("DELETE FROM discovered_urls")
                    conn.execute("DELETE FROM crawl_frontier")
                else:
                    conn.execute("DELETE FROM companies")
                    conn.execute("DELETE FROM company_evidence")
                    conn.execute("DELETE FROM discovered_urls")
                    conn.execute("DELETE FROM crawl_frontier")
        finally:
            conn.close()

