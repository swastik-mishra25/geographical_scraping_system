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


def pop_from_frontier(batch_size: int = 10, db_path: str = DATABASE_PATH) -> list[dict[str, Any]]:
    now = time.time()
    with _DB_LOCK:
        conn = _get_connection(db_path)
        try:
            with conn:
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
                        created_at, updated_at, last_verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
