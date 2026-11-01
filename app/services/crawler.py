"""Autonomous public website crawler with internal link prioritization and compliance safety."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import (
    CRAWLER_MAX_PAGES_PER_DOMAIN,
    CRAWLER_TIMEOUT_SECONDS,
    HEADERS,
)
from app.services.crawl_policy import (
    apply_domain_politeness,
    check_crawl_permission,
    detect_anti_bot_or_auth,
)
from app.services.url_frontier import normalize_url

TARGET_PAGE_PATTERNS = {
    "about": re.compile(r"/(about|who-we-are|company|agency)", re.I),
    "services": re.compile(r"/(services|what-we-do|solutions|expertise)", re.I),
    "contact": re.compile(r"/(contact|reach-us|get-in-touch|locations|branches|offices)", re.I),
    "case_studies": re.compile(r"/(case-studies|portfolio|clients|work)", re.I),
}

_SESSION = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=32,
    pool_maxsize=32,
    max_retries=Retry(total=1, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]),
)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)
_SESSION.headers.update(HEADERS)


def _is_same_domain(url1: str, url2: str) -> bool:
    try:
        d1 = urlsplit(url1).netloc.lower().replace("www.", "")
        d2 = urlsplit(url2).netloc.lower().replace("www.", "")
        return d1 == d2
    except Exception:
        return False


class CrawledPage:
    def __init__(self, url: str, page_type: str, title: str, html: str, text: str, soup: BeautifulSoup):
        self.url = url
        self.page_type = page_type
        self.title = title
        self.html = html
        self.text = text
        self.soup = soup


def crawl_website(
    start_url: str,
    max_pages: int = CRAWLER_MAX_PAGES_PER_DOMAIN,
) -> dict[str, Any]:
    """Crawl permitted company website pages starting at homepage and following business links."""
    start_norm = normalize_url(start_url)
    domain = urlsplit(start_norm).netloc.lower()

    result: dict[str, Any] = {
        "root_url": start_norm,
        "domain": domain,
        "crawled_pages": [],
        "status": "completed",
        "error": "",
        "combined_text": "",
        "page_titles": [],
    }

    queue: list[tuple[str, str, int]] = [(start_norm, "homepage", 0)]
    visited_urls: set[str] = set()
    pages_crawled = 0

    while queue and pages_crawled < max_pages:
        current_url, page_type, depth = queue.pop(0)
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        # 1. Crawl policy and SSRF check
        permitted, reason = check_crawl_permission(current_url)
        if not permitted:
            if pages_crawled == 0:
                result["status"] = "blocked"
                result["error"] = reason
                return result
            continue

        # 2. Politeness delay
        apply_domain_politeness(domain)

        # 3. HTTP GET
        try:
            resp = _SESSION.get(
                current_url,
                timeout=(2.5, CRAWLER_TIMEOUT_SECONDS),
                allow_redirects=True,
            )
        except Exception as exc:
            if pages_crawled == 0:
                result["status"] = "failed"
                result["error"] = f"Connection failed: {exc}"
                return result
            continue

        # 4. Anti-bot / Authentication detection
        is_blocked, block_reason = detect_anti_bot_or_auth(resp.status_code, resp.text)
        if is_blocked:
            result["status"] = "blocked"
            result["error"] = block_reason
            return result

        if not resp.ok:
            continue

        # 5. Parse page content
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        body_text = soup.get_text(" ", strip=True)

        page_record = {
            "url": current_url,
            "page_type": page_type,
            "title": title,
            "text": body_text[:15000],
            "soup": soup,
        }
        result["crawled_pages"].append(page_record)
        result["combined_text"] += f" [{page_type.upper()}] " + body_text[:8000]
        if title and title not in result["page_titles"]:
            result["page_titles"].append(title)
        pages_crawled += 1

        # 6. Discover priority internal links (Contact, About, Services, Branches)
        if depth < 1:  # Only explore 1 level from homepage
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                target_url = urljoin(resp.url, href)
                target_norm = normalize_url(target_url)

                if not _is_same_domain(resp.url, target_norm):
                    continue
                if target_norm in visited_urls:
                    continue

                path = urlsplit(target_norm).path.lower()
                discovered_type = None
                for p_type, pattern in TARGET_PAGE_PATTERNS.items():
                    if pattern.search(path):
                        discovered_type = p_type
                        break

                if discovered_type:
                    queue.append((target_norm, discovered_type, depth + 1))

    return result

