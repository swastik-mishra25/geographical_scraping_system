"""Persistent URL frontier for autonomous public-web crawling with priority queuing."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from app.config import CRAWLER_MAX_DEPTH, CRAWLER_MAX_PAGES_PER_DOMAIN
from app.services.persistence import (
    pop_from_frontier,
    push_to_frontier,
    save_discovered_url,
    update_frontier_item,
)

HIGH_PRIORITY_TERMS = {
    "contact": 95,
    "contact-us": 95,
    "about": 85,
    "about-us": 85,
    "services": 80,
    "our-services": 80,
    "branches": 90,
    "locations": 90,
    "office": 85,
    "case-studies": 70,
    "portfolio": 70,
}


def normalize_url(url: str) -> str:
    """Normalize URL by stripping fragments and trailing slashes."""
    if not url:
        return ""
    clean = url.strip()
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parts = urlsplit(clean)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parts.path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        query = parts.query
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return clean


def calculate_url_priority(url: str, depth: int = 0) -> int:
    """Calculate queue priority for an approved URL based on depth and business relevance."""
    parts = urlsplit(url)
    path = parts.path.lower()

    if path in ("", "/"):
        return 100 - (depth * 10)

    score = 50 - (depth * 10)
    for term, weight in HIGH_PRIORITY_TERMS.items():
        if term in path:
            score = max(score, weight - (depth * 5))
    return max(1, score)


class UrlFrontier:
    """High-level wrapper around the persistent SQLite crawl frontier."""

    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self._domain_page_counts: dict[str, int] = {}

    def add_url(
        self,
        raw_url: str,
        depth: int = 0,
        query: str = "",
        discovery_method: str = "public_web",
        relevance_status: str = "approved",
    ) -> bool:
        """Add candidate URL to frontier if within depth and domain budget limits."""
        if depth > CRAWLER_MAX_DEPTH:
            return False

        norm_url = normalize_url(raw_url)
        if not norm_url:
            return False

        domain = urlsplit(norm_url).netloc.lower()
        if not domain:
            return False

        current_count = self._domain_page_counts.get(domain, 0)
        if current_count >= CRAWLER_MAX_PAGES_PER_DOMAIN:
            return False

        url_id = save_discovered_url(
            normalized_url=norm_url,
            domain=domain,
            discovery_query=query,
            discovery_method=discovery_method,
            relevance_status=relevance_status,
        )

        prio = calculate_url_priority(norm_url, depth=depth)
        pushed = push_to_frontier(
            url=norm_url,
            domain=domain,
            url_id=url_id,
            priority=prio,
            depth=depth,
        )
        if pushed:
            self._domain_page_counts[domain] = current_count + 1
        return pushed

    def fetch_batch(self, batch_size: int = 10) -> list[dict[str, Any]]:
        """Fetch pending items from persistent queue ordered by priority."""
        return pop_from_frontier(batch_size=batch_size)

    def mark_completed(self, frontier_id: int) -> None:
        update_frontier_item(frontier_id=frontier_id, status="completed")

    def mark_blocked(self, frontier_id: int, reason: str) -> None:
        update_frontier_item(frontier_id=frontier_id, status="blocked", last_error=reason)

    def mark_failed(self, frontier_id: int, error: str, retry: bool = False) -> None:
        update_frontier_item(frontier_id=frontier_id, status="failed", last_error=error, retry=retry)

