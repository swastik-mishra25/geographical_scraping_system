"""Autonomous public website crawler with internal link prioritization and compliance safety."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    "contact": re.compile(r"(contact|reach-us|get-in-touch|locations|branches|offices|connect)", re.I),
    "about": re.compile(r"(about|who-we-are|company|agency|our-story|team|leadership)", re.I),
    "services": re.compile(r"(services|what-we-do|solutions|expertise|capabilities|offerings)", re.I),
    "case_studies": re.compile(r"(case-studies|portfolio|clients|work)", re.I),
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


def _fetch_url_resilient(current_url: str) -> requests.Response:
    """Perform HTTP GET with automatic www-prefix and SSL verification fallbacks."""
    timeout_tuple = (2.5, CRAWLER_TIMEOUT_SECONDS)
    try:
        return _SESSION.get(current_url, timeout=timeout_tuple, allow_redirects=True)
    except requests.exceptions.SSLError:
        try:
            return _SESSION.get(current_url, timeout=timeout_tuple, allow_redirects=True, verify=False)
        except Exception:
            pass
    except Exception:
        pass

    # Fallback: try toggling www. subdomain if bare domain failed DNS/SSL
    parts = urlsplit(current_url)
    host = parts.netloc.lower()
    alt_host = host[4:] if host.startswith("www.") else f"www.{host}"
    alt_url = urlunsplit((parts.scheme, alt_host, parts.path or "/", parts.query, ""))
    try:
        return _SESSION.get(alt_url, timeout=timeout_tuple, allow_redirects=True)
    except requests.exceptions.SSLError:
        return _SESSION.get(alt_url, timeout=timeout_tuple, allow_redirects=True, verify=False)


def _extract_rich_page_text(soup: BeautifulSoup) -> str:
    """Extract visible body text plus SEO meta tags, JSON-LD blocks, and map iframe hints."""
    meta_parts: list[str] = []
    for meta in soup.find_all("meta"):
        name_attr = (meta.get("name") or meta.get("property") or "").lower()
        if any(k in name_attr for k in ("description", "keywords", "title", "site_name", "locality", "region")):
            content = (meta.get("content") or "").strip()
            if content:
                meta_parts.append(content)

    # Extract embedded Google Maps iframe location queries if present
    for iframe in soup.find_all("iframe", src=True):
        src = unquote(iframe["src"])
        if "maps" in src.lower() or "google" in src.lower():
            meta_parts.append(src)

    # Include JSON-LD structured data text so address/telephone/services are searchable
    for script in soup.find_all("script", type="application/ld+json"):
        if script.string:
            meta_parts.append(script.string.strip()[:3000])

    body_text = soup.get_text(" ", strip=True)
    if meta_parts:
        return " | ".join(meta_parts) + " | " + body_text
    return body_text


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
    queued_urls: set[str] = {start_norm}
    pages_crawled = 0

    while queue and pages_crawled < max_pages:
        current_url, page_type, depth = queue.pop(0)
        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        # 1. Crawl policy and SSRF check (verified on domain entry)
        if pages_crawled == 0:
            permitted, reason = check_crawl_permission(current_url)
            if not permitted:
                result["status"] = "blocked"
                result["error"] = reason
                return result

        # 2. Politeness delay
        apply_domain_politeness(domain)

        # 3. HTTP GET with automatic www and SSL fallback
        try:
            resp = _fetch_url_resilient(current_url)
        except Exception as exc:
            if pages_crawled == 0:
                result["status"] = "failed"
                result["error"] = f"Connection failed: {exc}"
                return result
            continue

        # 4. Anti-bot / Authentication detection
        is_blocked, block_reason = detect_anti_bot_or_auth(resp.status_code, resp.text)
        if is_blocked:
            if pages_crawled == 0:
                result["status"] = "blocked"
                result["error"] = block_reason
                return result
            continue

        if not resp.ok:
            continue

        # 5. Parse page content (including meta tags, JSON-LD, and map iframes)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        body_text = _extract_rich_page_text(soup)

        page_record = {
            "url": current_url,
            "page_type": page_type,
            "title": title,
            "text": body_text[:18000],
            "soup": soup,
        }
        result["crawled_pages"].append(page_record)
        result["combined_text"] += f" [{page_type.upper()}] " + body_text[:10000]
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
                if target_norm in visited_urls or target_norm in queued_urls:
                    continue

                path = urlsplit(target_norm).path.lower()
                link_label = a_tag.get_text(" ", strip=True).lower()
                discovered_type = None
                for p_type, pattern in TARGET_PAGE_PATTERNS.items():
                    if pattern.search(path) or (len(link_label) < 35 and pattern.search(link_label)):
                        discovered_type = p_type
                        break

                if discovered_type:
                    queued_urls.add(target_norm)
                    if discovered_type == "contact":
                        queue.insert(0, (target_norm, discovered_type, depth + 1))
                    else:
                        queue.append((target_norm, discovered_type, depth + 1))

    return result

