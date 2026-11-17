"""Generic Public-Web Discovery Gateway independent of fixed directory providers.

Features dynamic AI-powered discovery (Gemini Flash), live multi-engine search (Bing + DDG),
deep directory/listicle link harvesting, and an externalized dynamic regional catalog.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from bs4 import BeautifulSoup

from app.config import (
    DATA_DIR,
    DISCOVERY_MAX_URLS,
    DISCOVERY_TIMEOUT_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    HEADERS,
)
from app.services.crawl_policy import check_crawl_permission
from app.services.url_frontier import normalize_url

logger = logging.getLogger("dakini.discovery")

DIRECTORY_DOMAINS = {
    "goodfirms.co", "clutch.co", "designrush.com", "topdevelopers.co", "f6s.com",
    "themanifest.com", "sortlist.com", "bark.com", "upwork.com", "freelancer.com",
    "fiverr.com", "crunchbase.com", "zoominfo.com", "apollo.io", "dnb.com",
    "zaubacorp.com", "tofler.in", "instafinancials.com", "digit.in", "g2.com",
    "capterra.com", "trustpilot.com", "softwareadvice.com", "bestbuy.com",
    "nykaafashion.com", "socialoffline.in", "socialclub.rockstargames.com", "etymonline.com",
    "seo.com", "searchengineland.com", "moz.com", "bestundertaking.net",
    "semrush.com", "ahrefs.com",
}

EXCLUDED_DOMAINS = {
    "google.com", "google.co.in", "bing.com", "duckduckgo.com", "yahoo.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com", "quora.com", "reddit.com", "medium.com",
    "wikipedia.org", "wikidata.org", "wikimedia.org",
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com",
    "yelp.com", "tripadvisor.com", "glassdoor.com", "indeed.com", "naukri.com",
    "github.com", "play.google.com", "apps.apple.com", "amazon.in", "flipkart.com",
    "threads.net", "wa.me", "whatsapp.com",
    # Academic, library, government, dictionary, retail & non-company archives
    "viaf.org", "idref.fr", "d-nb.info", "yale.edu", "bibliotheken.nl",
    "imdb.com", "rottentomatoes.com", "dictionary.cambridge.org", "merriam-webster.com",
    "collinsdictionary.com", "thefreedictionary.com", "vocabulary.com", "wiktionary.org",
    "reliancedigital.in", "myntra.com", "amazon.com", "cisco.com", "simplilearn.com",
    "geeksforgeeks.org", "tutorialspoint.com", "softonic.com", "computerhope.com",
} | DIRECTORY_DOMAINS

DISALLOWED_TLDS = {".edu", ".gov", ".mil", ".ac.in", ".edu.in", ".gov.in", ".nic.in"}


# =========================================================================
# Dynamic Regional Catalog Loader (Externalized from Python Source Code)
# =========================================================================

_CATALOG_CACHE: Optional[dict[str, Any]] = None


def load_seed_catalog() -> dict[str, Any]:
    """Dynamically load regional business seeds from external JSON catalog or database."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    catalog_path = Path(DATA_DIR) / "seed_catalog.json"
    cat: dict[str, Any] = {"city_seeds": {}, "locality_seeds": {}}
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    cat["city_seeds"] = loaded.get("city_seeds", {})
                    cat["locality_seeds"] = loaded.get("locality_seeds", {})
        except Exception as exc:
            logger.warning("Failed to load external seed catalog: %s", exc)

    # Dynamically augment catalog with verified companies from the master SQLite database
    db_path = Path(DATA_DIR) / "dakini_discovery.db"
    if db_path.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(
                "SELECT city, locality, company_name, website FROM companies "
                "WHERE website IS NOT NULL AND website != '' AND execution_status = 'verified'"
            )
            for c_city, c_loc, c_name, c_site in cur.fetchall():
                c_clean = (c_city or "").strip().lower()
                l_clean = (c_loc or "").strip().lower()
                dom = _extract_domain(c_site)
                if not dom or not _is_company_candidate_domain(dom):
                    continue
                item = {"url": c_site, "domain": dom, "title": c_name or dom, "city": c_city, "locality": c_loc}
                # Add to city list if not present
                if c_clean:
                    city_list = cat["city_seeds"].setdefault(c_clean, [])
                    if not any(x.get("domain") == dom for x in city_list):
                        city_list.append(item)
                # Add to locality list if present
                if c_clean and l_clean:
                    loc_key = f"{c_clean}:{l_clean}"
                    loc_list = cat["locality_seeds"].setdefault(loc_key, [])
                    if not any(x.get("domain") == dom for x in loc_list):
                        loc_list.append(item)
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    _CATALOG_CACHE = cat
    return _CATALOG_CACHE


class _DynamicCitySeedsProxy(dict):
    """Dynamic dict proxy providing backward-compatible access to externalized city seeds."""

    def __getitem__(self, key: str) -> list[dict[str, str]]:
        return load_seed_catalog().get("city_seeds", {}).get(key.lower(), [])

    def get(self, key: str, default: Any = None) -> Any:
        return load_seed_catalog().get("city_seeds", {}).get(key.lower(), default)

    def items(self):
        return load_seed_catalog().get("city_seeds", {}).items()

    def values(self):
        return load_seed_catalog().get("city_seeds", {}).values()

    def keys(self):
        return load_seed_catalog().get("city_seeds", {}).keys()

    def __contains__(self, key: object) -> bool:
        return str(key).lower() in load_seed_catalog().get("city_seeds", {})


class _DynamicLocalitySeedsProxy(dict):
    """Dynamic dict proxy providing backward-compatible access to externalized locality seeds."""

    def __getitem__(self, key: Any) -> list[dict[str, str]]:
        str_key = f"{key[0].lower()}:{key[1].lower()}" if isinstance(key, tuple) else str(key).lower()
        return load_seed_catalog().get("locality_seeds", {}).get(str_key, [])

    def get(self, key: Any, default: Any = None) -> Any:
        str_key = f"{key[0].lower()}:{key[1].lower()}" if isinstance(key, tuple) else str(key).lower()
        return load_seed_catalog().get("locality_seeds", {}).get(str_key, default)

    def items(self):
        res = []
        for k, v in load_seed_catalog().get("locality_seeds", {}).items():
            parts = k.split(":", 1)
            tup = (parts[0], parts[1]) if len(parts) == 2 else (k, "")
            res.append((tup, v))
        return res

    def values(self):
        return load_seed_catalog().get("locality_seeds", {}).values()

    def __contains__(self, key: object) -> bool:
        str_key = f"{key[0].lower()}:{key[1].lower()}" if isinstance(key, tuple) else str(key).lower()
        return str_key in load_seed_catalog().get("locality_seeds", {})


# Exported proxies for backward compatibility (Zero hardcoded lines inside source code)
INDIAN_DIGITAL_MARKETING_SEEDS = _DynamicCitySeedsProxy()
INDIAN_LOCALITY_SEEDS = _DynamicLocalitySeedsProxy()


# =========================================================================
# Domain Extraction & Candidate Safety Validation
# =========================================================================

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
    for tld in DISALLOWED_TLDS:
        if domain.endswith(tld):
            return False
    for ex in EXCLUDED_DOMAINS:
        if domain.endswith("." + ex):
            return False
    return True


def decode_bing_url(bing_url: str) -> str:
    """Decode base64 destination URL embedded in Bing search results (u=a1...)."""
    parsed = urllib.parse.urlsplit(bing_url)
    params = urllib.parse.parse_qs(parsed.query)
    u_val = params.get("u", [""])[0]
    if not u_val:
        return bing_url
    raw = u_val[2:] if u_val.startswith(("a1", "a0")) else u_val
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="ignore")
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    return bing_url


# =========================================================================
# AI-Powered Dynamic Web Discovery (Gemini Flash Grounded Research)
# =========================================================================

def discover_via_gemini_ai(
    industry: str,
    city: str,
    locality: str = "",
    country: str = "India",
    max_results: int = 30,
) -> list[dict[str, Any]]:
    """Dynamically discover authentic regional corporate websites using Gemini Flash."""
    api_key = (os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY).strip()
    if not api_key:
        return []

    model_name = (os.getenv("GEMINI_MODEL", "") or GEMINI_MODEL or "gemini-2.0-flash").strip()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    loc_str = f"in {locality}, {city}" if locality else f"in {city}"
    prompt = (
        f"You are an autonomous corporate research intelligence engine. "
        f"Identify {max_results} authentic, live, operating corporate business websites for the '{industry}' "
        f"industry located {loc_str}, {country}.\n"
        f"STRICT RULES:\n"
        f"1. Return ONLY real corporate homepages with official website URLs (https://...).\n"
        f"2. Exclude aggregators/directories (e.g. Justdial, Sulekha, Indiamart, Yelp, Clutch, Goodfirms).\n"
        f"3. Exclude social media profiles (LinkedIn, Facebook, Instagram, Twitter, YouTube).\n"
        f"4. Return strict JSON with a 'companies' list containing:\n"
        f"   - 'company_name': official company brand name\n"
        f"   - 'url': official homepage URL\n"
        f"   - 'domain': root domain without www\n"
        f"   - 'locality': commercial district or city area\n"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        resp = requests.post(
            endpoint,
            params={"key": api_key},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=12.0,
        )
        if not resp.ok:
            logger.warning("Gemini discovery HTTP error: %s - %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        raw_text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )
        parsed = json.loads(raw_text)
        companies_list = parsed.get("companies", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])

        for item in companies_list:
            if not isinstance(item, dict):
                continue
            u = (item.get("url") or "").strip()
            d = (item.get("domain") or _extract_domain(u)).lower()
            name = (item.get("company_name") or d).strip()
            if not u.startswith("http"):
                u = f"https://{d}" if d else ""
            if d and d not in seen and _is_company_candidate_domain(d):
                seen.add(d)
                results.append({
                    "url": normalize_url(u),
                    "domain": d,
                    "title": f"{name} - {industry} {city}",
                    "query": f"gemini_ai:{industry}:{city}",
                    "method": "gemini_ai_grounded_discovery",
                })
                if len(results) >= max_results:
                    break
    except Exception as exc:
        logger.warning("Gemini dynamic discovery failed: %s", exc)

    return results


# =========================================================================
# Modular Public Web Discovery Gateway (Multi-Engine)
# =========================================================================

class PublicWebDiscoveryGateway:
    """Modular public-web discovery engine combining AI, multi-engine search, and dynamic directories."""

    def __init__(self, timeout: float = DISCOVERY_TIMEOUT_SECONDS):
        self.timeout = min(2.5, timeout)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._handshake_done = False
        self._ddg_circuit_broken = False
        self._ddg_failures = 0

    def discover_from_bing_search(
        self,
        query: str,
        max_results: int = 25,
        listicle_sink: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Dynamically search and decode candidate corporate websites via Bing with offset pagination."""
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        clean_q = query.strip()
        if not clean_q:
            return []

        pages_to_fetch = min(4, max(1, (max_results + 9) // 10))
        for page_idx in range(pages_to_fetch):
            if len(results) >= max_results:
                break
            first = page_idx * 10 + 1
            search_url = f"https://www.bing.com/search?q={urllib.parse.quote(clean_q)}&count=25&first={first}"
            try:
                resp = self.session.get(search_url, timeout=min(4.0, self.timeout + 1.5))
                if resp.status_code in (429, 503):
                    logger.warning("[discovery] Bing rate-limited (HTTP %d). Retrying query '%s'...", resp.status_code, clean_q)
                    time.sleep(1.0)
                    resp = self.session.get(search_url, timeout=min(4.0, self.timeout + 1.5))
                if not resp.ok:
                    logger.debug("[discovery] Bing HTTP %d for query '%s' page %d", resp.status_code, clean_q, page_idx + 1)
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                items = soup.select("li.b_algo")
                if not items:
                    break

                new_on_page = 0
                for li in items:
                    h2 = li.select_one("h2 a")
                    if not h2 or not h2.get("href"):
                        continue
                    raw_href = h2["href"].strip()
                    real_url = decode_bing_url(raw_href)
                    dom = _extract_domain(real_url)

                    # Harvest directory/listicle URLs into sink for deep outbound extraction
                    if listicle_sink is not None and real_url.startswith("http"):
                        lower_real = real_url.lower()
                        is_listicle = any(
                            tag in lower_real
                            for tag in ("/directory/", "/top-", "-agencies", "/agencies/", "/agency/", "/companies/", "/blog/")
                        ) or (dom in DIRECTORY_DOMAINS)
                        if is_listicle and real_url not in listicle_sink:
                            listicle_sink.append(real_url)

                    if not dom or dom in seen or not _is_company_candidate_domain(dom):
                        continue

                    seen.add(dom)
                    new_on_page += 1
                    title = h2.get_text(strip=True) or dom
                    results.append({
                        "url": normalize_url(real_url),
                        "domain": dom,
                        "title": title,
                        "query": query,
                        "method": "bing_dynamic_search",
                    })
                    if len(results) >= max_results:
                        break

                if new_on_page == 0 and page_idx > 0:
                    break
                time.sleep(0.08)
            except Exception as exc:
                logger.debug("Bing search error for query '%s' page %d: %s", clean_q, page_idx + 1, exc)
                break

        return results

    def _ensure_session_handshake(self) -> None:
        """Perform lightweight handshake to warm session cookies."""
        if not self._handshake_done and not self._ddg_circuit_broken:
            try:
                self.session.get("https://html.duckduckgo.com/html/", timeout=min(2.0, self.timeout))
                self.session.headers["Sec-Fetch-Site"] = "same-origin"
                self._handshake_done = True
            except Exception:
                self._ddg_circuit_broken = True

    def discover_from_duckduckgo_lite(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo Lite search."""
        if self._ddg_circuit_broken:
            return []
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={
                    "Referer": "https://lite.duckduckgo.com/",
                    "Origin": "https://lite.duckduckgo.com",
                },
                timeout=min(2.0, self.timeout),
            )
            if not resp.ok or resp.status_code == 202:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result-link"):
                href = link.get("href", "").strip()
                if not href:
                    continue

                if "duckduckgo.com/l/?uddg=" in href:
                    parsed = parse_qs(urlsplit(href).query)
                    target = parsed.get("uddg", [None])[0]
                    if target:
                        href = unquote(target)

                if not href.startswith("http"):
                    continue

                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if dom and _is_company_candidate_domain(dom):
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": query,
                        "method": "duckduckgo_lite",
                        "title": link.get_text(strip=True) or dom,
                    })

                if len(results) >= max_results:
                    break
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
            self._ddg_failures += 1
            if self._ddg_failures >= 2:
                self._ddg_circuit_broken = True
            return []
        except Exception:
            return []
        return results

    def discover_from_duckduckgo_html(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo public HTML search."""
        if self._ddg_circuit_broken:
            return []
        self._ensure_session_handshake()
        if self._ddg_circuit_broken:
            return []
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                headers={
                    "Referer": "https://html.duckduckgo.com/",
                    "Origin": "https://html.duckduckgo.com",
                },
                timeout=min(2.0, self.timeout),
            )
            if not resp.ok or resp.status_code == 202:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result__url"):
                href = link.get("href", "").strip()
                if not href:
                    continue

                if "duckduckgo.com/l/?uddg=" in href:
                    parsed = parse_qs(urlsplit(href).query)
                    target = parsed.get("uddg", [None])[0]
                    if target:
                        href = unquote(target)

                if not href.startswith("http"):
                    continue

                norm = normalize_url(href)
                dom = _extract_domain(norm)
                if dom and _is_company_candidate_domain(dom):
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": query,
                        "method": "duckduckgo_html",
                        "title": link.get_text(strip=True) or dom,
                    })

                if len(results) >= max_results:
                    break
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
            self._ddg_failures += 1
            if self._ddg_failures >= 2:
                self._ddg_circuit_broken = True
            return []
        except Exception:
            return []
        return results

    def harvest_listicle_domains(self, page_url: str, max_extract: int = 25) -> list[dict[str, Any]]:
        """Extract outbound candidate corporate domains from directory or roundup listicle pages."""
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.get(page_url, timeout=max(4.0, self.timeout))
            if not resp.ok:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            seen_doms: set[str] = set()
            page_dom = _extract_domain(page_url)
            for a in soup.select("a"):
                href = a.get("href", "").strip()
                if not href.startswith("http"):
                    continue
                norm = normalize_url(href)
                dom = _extract_domain(norm)
                # Ignore self-referential links back to the aggregator directory itself
                if dom and dom != page_dom and not dom.endswith("." + page_dom) and dom not in seen_doms and _is_company_candidate_domain(dom):
                    seen_doms.add(dom)
                    results.append({
                        "url": norm,
                        "domain": dom,
                        "query": f"listicle:{page_dom}",
                        "method": "listicle_link_harvester",
                        "title": a.get_text(strip=True) or dom,
                    })
                if len(results) >= max_extract:
                    break
        except Exception:
            pass
        return results

    def discover_from_curated_seeds(
        self,
        city: str,
        locality: str = "",
        industry_category: str = "Digital Marketing",
        excluded_domains: Optional[set[str]] = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Discover verified regional business homepages from the dynamic seed registry and database."""
        results: list[dict[str, Any]] = []
        clean_city = (city or "").strip().lower()
        clean_loc = (locality or "").strip().lower()
        excluded = {d.lower() for d in (excluded_domains or set())}
        seen_domains: set[str] = set()

        cat = load_seed_catalog()
        loc_seeds = cat.get("locality_seeds", {})
        city_seeds = cat.get("city_seeds", {})

        # 1. Match locality-specific catalog first if locality is provided
        if clean_loc:
            for l_key, seeds in loc_seeds.items():
                parts = l_key.split(":", 1)
                c_k = parts[0].lower()
                l_k = parts[1].lower() if len(parts) > 1 else ""
                if (c_k in clean_city or clean_city in c_k) and (l_k in clean_loc or clean_loc in l_k):
                    for s in seeds:
                        dom = s["domain"].lower()
                        if dom not in excluded and dom not in seen_domains and _is_company_candidate_domain(dom):
                            seen_domains.add(dom)
                            results.append({
                                "url": normalize_url(s["url"]),
                                "domain": dom,
                                "query": f"locality_seed:{clean_loc}",
                                "method": "curated_locality_registry",
                                "title": s.get("title", dom),
                            })
                            if len(results) >= max_results:
                                break
                    if len(results) >= max_results:
                        break
            if results:
                return results

        # 2. Add city-level seeds if locality was not specified or yielded 0 candidates
        if len(results) < max_results:
            for city_key, seeds in city_seeds.items():
                if city_key in clean_city or clean_city in city_key:
                    for s in seeds:
                        dom = s["domain"].lower()
                        if dom not in excluded and dom not in seen_domains and _is_company_candidate_domain(dom):
                            seen_domains.add(dom)
                            results.append({
                                "url": normalize_url(s["url"]),
                                "domain": dom,
                                "query": f"seed:{city_key}",
                                "method": "curated_regional_registry",
                                "title": s.get("title", dom),
                            })
                            if len(results) >= max_results:
                                break

        # 3. National baseline if scope is wide or unknown city
        if not results and (not clean_city or clean_city in ("all", "india", "national")):
            for seeds in city_seeds.values():
                for s in seeds[:5]:
                    dom = s["domain"].lower()
                    if dom not in excluded and dom not in seen_domains and _is_company_candidate_domain(dom):
                        seen_domains.add(dom)
                        results.append({
                            "url": normalize_url(s["url"]),
                            "domain": dom,
                            "query": "seed:national",
                            "method": "curated_national_registry",
                            "title": s.get("title", dom),
                        })

        return results

    def run_discovery(
        self,
        queries: list[dict[str, Any]],
        max_urls: int = DISCOVERY_MAX_URLS,
        city: str = "",
        locality: str = "",
        category: str = "Digital Marketing",
        excluded_domains: Optional[set[str]] = None,
        allow_synthetic_fallback: bool = False,
        step_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute multi-tier dynamic discovery across AI research, live web search,
        directory harvesting, and verified regional catalog registry.
        """
        discovered_candidates: list[dict[str, Any]] = []
        seen_domains: set[str] = {d.lower() for d in (excluded_domains or set())}

        # -----------------------------------------------------------------
        # Stage 1: AI-Powered Dynamic Web Discovery (if Gemini Key available)
        # -----------------------------------------------------------------
        api_key = (os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY).strip()
        if api_key and city:
            if step_callback:
                step_callback({
                    "stage": "discovery_ai",
                    "message": f"AI Discovery active: Researching {category} in {locality or city}...",
                })
            ai_hits = discover_via_gemini_ai(
                industry=category,
                city=city,
                locality=locality,
                max_results=min(25, max_urls),
            )
            for hit in ai_hits:
                dom = hit["domain"].lower()
                if dom not in seen_domains and _is_company_candidate_domain(dom):
                    seen_domains.add(dom)
                    discovered_candidates.append(hit)
                if len(discovered_candidates) >= max_urls:
                    break

        # -----------------------------------------------------------------
        # Stage 2: Dynamic Live Web Search Engine (Bing + DDG fallback)
        # -----------------------------------------------------------------
        listicle_candidates: list[str] = []
        for q_idx, q_item in enumerate(queries):
            if len(discovered_candidates) >= max_urls:
                break
            query_str = q_item.get("query", "")
            if not query_str:
                continue

            if step_callback:
                step_callback({
                    "stage": "discovery_searching",
                    "query": query_str,
                    "query_index": q_idx + 1,
                    "total_queries": len(queries),
                    "discovered_count": len(discovered_candidates),
                })

            # 2A. Live Bing Search with pagination and listicle harvesting sink
            search_quota = min(30, max(15, max_urls - len(discovered_candidates)))
            bing_hits = self.discover_from_bing_search(query_str, max_results=search_quota, listicle_sink=listicle_candidates)
            for hit in bing_hits:
                dom = hit["domain"]
                hit_url = hit["url"]
                if any(x in hit_url.lower() for x in ["/blog/", "/agencies/", "/top-", "-agencies", "/agency/", "/directory/", "/companies/"]):
                    if hit_url not in listicle_candidates:
                        listicle_candidates.append(hit_url)
                if dom not in seen_domains and _is_company_candidate_domain(dom):
                    seen_domains.add(dom)
                    discovered_candidates.append(hit)
                if len(discovered_candidates) >= max_urls:
                    break

            # 2B. Fallback to DuckDuckGo if Bing yielded fewer than required
            if len(discovered_candidates) < max_urls and not self._ddg_circuit_broken:
                ddg_hits = self.discover_from_duckduckgo_html(query_str, max_results=15)
                if not ddg_hits and not self._ddg_circuit_broken:
                    ddg_hits = self.discover_from_duckduckgo_lite(query_str, max_results=15)
                for hit in ddg_hits:
                    dom = hit["domain"]
                    hit_url = hit["url"]
                    if any(x in hit_url.lower() for x in ["/blog/", "/agencies/", "/top-", "-agencies", "/agency/"]):
                        listicle_candidates.append(hit_url)
                    if dom not in seen_domains and _is_company_candidate_domain(dom):
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)
                    if len(discovered_candidates) >= max_urls:
                        break

            time.sleep(0.05)

        # -----------------------------------------------------------------
        # Stage 3: Deep Link Harvest from Discovered Listicles & Directories
        # -----------------------------------------------------------------
        if len(discovered_candidates) < max_urls and listicle_candidates:
            for l_url in listicle_candidates[:12]:
                if len(discovered_candidates) >= max_urls:
                    break
                harvested = self.harvest_listicle_domains(l_url, max_extract=35)
                for h in harvested:
                    dom = h["domain"]
                    if dom not in seen_domains and _is_company_candidate_domain(dom):
                        seen_domains.add(dom)
                        discovered_candidates.append(h)
                    if len(discovered_candidates) >= max_urls:
                        break

        # -----------------------------------------------------------------
        # Stage 4: Verified Regional Catalog & SQLite Knowledge Base
        # -----------------------------------------------------------------
        if len(discovered_candidates) < max_urls and city:
            seed_hits = self.discover_from_curated_seeds(
                city=city,
                locality=locality,
                industry_category=category,
                excluded_domains=seen_domains,
                max_results=max_urls - len(discovered_candidates),
            )
            for hit in seed_hits:
                dom = hit["domain"].lower()
                if dom not in seen_domains and _is_company_candidate_domain(dom):
                    seen_domains.add(dom)
                    discovered_candidates.append(hit)
                if len(discovered_candidates) >= max_urls:
                    break
            if step_callback and discovered_candidates:
                loc_label = f" for {locality}" if locality else ""
                step_callback({
                    "stage": "discovery_seeds",
                    "discovered_count": len(discovered_candidates),
                    "message": f"Identified {len(discovered_candidates)} corporate domains{loc_label}",
                })

        return discovered_candidates[:max_urls]
