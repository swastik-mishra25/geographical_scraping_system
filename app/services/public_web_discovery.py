"""Generic Public-Web Discovery Gateway independent of fixed directory providers."""
from __future__ import annotations

import re
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from bs4 import BeautifulSoup

from app.config import (
    DISCOVERY_MAX_URLS,
    DISCOVERY_TIMEOUT_SECONDS,
    HEADERS,
)
from app.services.crawl_policy import check_crawl_permission
from app.services.url_frontier import normalize_url

EXCLUDED_DOMAINS = {
    "google.com", "google.co.in", "bing.com", "duckduckgo.com", "yahoo.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com", "quora.com", "reddit.com", "medium.com",
    "wikipedia.org", "wikidata.org", "wikimedia.org",
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com",
    "yelp.com", "tripadvisor.com", "glassdoor.com", "indeed.com", "naukri.com",
    "github.com", "play.google.com", "apps.apple.com", "amazon.in", "flipkart.com",
}


def _extract_domain(url: str) -> str:
    try:
        netloc = urlsplit(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split(":")[0]
    except Exception:
        return ""


def _is_company_candidate_domain(domain: str) -> bool:
    if not domain or "." not in domain:
        return False
    if domain in EXCLUDED_DOMAINS:
        return False
    for ex in EXCLUDED_DOMAINS:
        if domain.endswith("." + ex):
            return False
    return True


class PublicWebDiscoveryGateway:
    """Modular public-web discovery engine that obtains candidate URLs from permitted interfaces."""

    def __init__(self, timeout: float = DISCOVERY_TIMEOUT_SECONDS):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def discover_from_duckduckgo_html(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo public HTML search."""
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                timeout=self.timeout,
            )
            if not resp.ok:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result__url"):
                href = link.get("href", "").strip()
                if not href:
                    continue

                # DuckDuckGo wraps outbound links in /l/?uddg=<url>
                if "uddg=" in href:
                    parsed_query = parse_qs(urlsplit(href).query)
                    target = parsed_query.get("uddg", [None])[0]
                    if target:
                        href = unquote(target)

                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if _is_company_candidate_domain(dom):
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": query,
                        "method": "duckduckgo_html",
                        "title": link.get_text(strip=True),
                    })
                if len(results) >= max_results:
                    break
        except Exception:
            pass
        return results

    def discover_from_wikipedia_web_index(self, query: str, max_results: int = 15) -> list[dict[str, Any]]:
        """Discover external company homepages listed on public encyclopedic search results."""
        results: list[dict[str, Any]] = []
        try:
            api_url = "https://en.wikipedia.org/w/api.php"
            resp = self.session.get(
                api_url,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 10,
                },
                timeout=self.timeout,
            )
            if not resp.ok:
                return []

            items = resp.json().get("query", {}).get("search", []) or []
            for item in items:
                title = item.get("title", "")
                if not title:
                    continue
                parse_resp = self.session.get(
                    api_url,
                    params={
                        "action": "parse",
                        "page": title,
                        "prop": "externallinks",
                        "format": "json",
                    },
                    timeout=self.timeout,
                )
                if not parse_resp.ok:
                    continue

                links = parse_resp.json().get("parse", {}).get("externallinks", []) or []
                for link in links:
                    norm = normalize_url(str(link))
                    dom = _extract_domain(norm)
                    if _is_company_candidate_domain(dom):
                        results.append({
                            "url": norm,
                            "domain": dom,
                            "query": query,
                            "method": "wikipedia_web_index",
                            "title": title,
                        })
                if len(results) >= max_results:
                    break
        except Exception:
            pass
        return results

    def run_discovery(
        self,
        queries: list[dict[str, Any]],
        max_urls: int = DISCOVERY_MAX_URLS,
    ) -> list[dict[str, Any]]:
        """Execute discovery queries across generic public-web discovery interfaces and filter by crawl policy."""
        discovered_candidates: list[dict[str, Any]] = []
        seen_domains: set[str] = set()

        for q_item in queries:
            if len(discovered_candidates) >= max_urls:
                break
            query_str = q_item.get("query", "")

            # 1. Search via public web search interface
            ddg_hits = self.discover_from_duckduckgo_html(query_str, max_results=15)
            for hit in ddg_hits:
                dom = hit["domain"]
                if dom not in seen_domains:
                    permitted, reason = check_crawl_permission(hit["url"])
                    if permitted:
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)

            # 2. Corroborate via open web index
            if len(discovered_candidates) < max_urls:
                wiki_hits = self.discover_from_wikipedia_web_index(query_str, max_results=10)
                for hit in wiki_hits:
                    dom = hit["domain"]
                    if dom not in seen_domains:
                        permitted, reason = check_crawl_permission(hit["url"])
                        if permitted:
                            seen_domains.add(dom)
                            discovered_candidates.append(hit)

        return discovered_candidates[:max_urls]

