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
    # Academic, library, government & media non-agency archives
    "viaf.org", "idref.fr", "d-nb.info", "yale.edu", "bibliotheken.nl",
    "adelaidereview.com.au", "dailyreview.com.au", "helpmannawards.com.au",
    "aacta.org", "tvtonight.com.au", "people.com", "variety.com", "abc.net.au",
    "sydneyartsguide.com.au", "afca.org.au", "imdb.com", "rottentomatoes.com",
}

DISALLOWED_TLDS = {".edu", ".gov", ".mil", ".ac.in", ".edu.in", ".gov.in"}

# High-quality verified Indian Digital Marketing agencies catalog by city
INDIAN_DIGITAL_MARKETING_SEEDS: dict[str, list[dict[str, str]]] = {
    "mumbai": [
        {"url": "https://www.schbang.com", "domain": "schbang.com", "title": "Schbang - Integrated Marketing Solutions", "city": "Mumbai"},
        {"url": "https://www.watconsult.com", "domain": "watconsult.com", "title": "WATConsult - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.bcwebwise.com", "domain": "bcwebwise.com", "title": "BC Web Wise - Full Service Digital Agency", "city": "Mumbai"},
        {"url": "https://www.foxyngage.com", "domain": "foxyngage.com", "title": "FoxyMoron - Creative & Digital Agency", "city": "Mumbai"},
        {"url": "https://www.kinnectonline.com", "domain": "kinnectonline.com", "title": "Kinnect - Digital Marketing Company", "city": "Mumbai"},
        {"url": "https://www.interactiveavenues.com", "domain": "interactiveavenues.com", "title": "Interactive Avenues - Digital Media Agency", "city": "Mumbai"},
        {"url": "https://www.socialbeat.in", "domain": "socialbeat.in", "title": "Social Beat - Growth & Performance Marketing", "city": "Mumbai"},
        {"url": "https://www.puretech.com", "domain": "puretech.com", "title": "Puretech Digital - Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.digichefs.com", "domain": "digichefs.com", "title": "DigiChefs - Performance Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.braincandy.in", "domain": "braincandy.in", "title": "Brain Candy - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.capsicummediaworks.com", "domain": "capsicummediaworks.com", "title": "Capsicum Mediaworks - Web & SEO Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.whitebanana.in", "domain": "whitebanana.in", "title": "White Banana - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.creativelandasia.com", "domain": "creativelandasia.com", "title": "Creativeland Asia - Brand & Digital Agency", "city": "Mumbai"},
        {"url": "https://www.ting.in", "domain": "ting.in", "title": "Ting - Creative & Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.mirumagency.com", "domain": "mirumagency.com", "title": "Mirum India - Digital Marketing Agency", "city": "Mumbai"},
        {"url": "https://www.monk-e.in", "domain": "monk-e.in", "title": "Monk Entertainment - Digital Marketing Mumbai", "city": "Mumbai"},
        {"url": "https://www.adfactorspr.com", "domain": "adfactorspr.com", "title": "Adfactors PR & Digital", "city": "Mumbai"},
        {"url": "https://www.armdigital.in", "domain": "armdigital.in", "title": "ARM Digital - Digital Marketing & Content Agency", "city": "Mumbai"},
        {"url": "https://www.growthhackers.digital", "domain": "growthhackers.digital", "title": "Growth Hackers Digital", "city": "Mumbai"},
        {"url": "https://www.brewmyidea.com", "domain": "brewmyidea.com", "title": "Brew My Idea - Digital Marketing Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.digitallatte.com", "domain": "digitallatte.com", "title": "Digital Latte - 360 Creative & Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.promotedge.com", "domain": "promotedge.com", "title": "PromotEdge - Digital Agency", "city": "Mumbai"},
        {"url": "https://www.fruitbowlmedia.com", "domain": "fruitbowlmedia.com", "title": "Fruitbowl Digital - Full Service Digital Agency Mumbai", "city": "Mumbai"},
        {"url": "https://www.thebrandbee.com", "domain": "thebrandbee.com", "title": "The Brand Bee - Digital Marketing Agency", "city": "Mumbai"},
    ],
    "pune": [
        {"url": "https://www.dimakhconsultants.com", "domain": "dimakhconsultants.com", "title": "Dimakh Consultants - Digital Marketing Pune", "city": "Pune"},
        {"url": "https://www.dreamworth.in", "domain": "dreamworth.in", "title": "Dreamworth Solutions - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.tempestadvertising.com", "domain": "tempestadvertising.com", "title": "Tempest Advertising - Digital & Creative Pune", "city": "Pune"},
        {"url": "https://www.scrumdigital.com", "domain": "scrumdigital.com", "title": "Scrum Digital Agency Pune", "city": "Pune"},
        {"url": "https://www.brightbrain.in", "domain": "brightbrain.in", "title": "Bright Brain - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.brandloom.com", "domain": "brandloom.com", "title": "BrandLoom Consulting - Digital Marketing Agency", "city": "Pune"},
        {"url": "https://www.aarnaology.com", "domain": "aarnaology.com", "title": "Aarna Systems - Digital Marketing Company Pune", "city": "Pune"},
        {"url": "https://www.ikf.co.in", "domain": "ikf.co.in", "title": "I Knowledge Factory - Digital Marketing Agency Pune", "city": "Pune"},
        {"url": "https://www.technooyster.com", "domain": "technooyster.com", "title": "Techno Oyster - Digital Marketing Agency Pune", "city": "Pune"},
    ],
    "bengaluru": [
        {"url": "https://www.socialbeat.in", "domain": "socialbeat.in", "title": "Social Beat - Digital Marketing Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.growthhackers.digital", "domain": "growthhackers.digital", "title": "Growth Hackers Digital Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.webchutney.com", "domain": "webchutney.com", "title": "Dentsu Webchutney - Digital Creative Agency", "city": "Bengaluru"},
        {"url": "https://www.socialpanga.com", "domain": "socialpanga.com", "title": "Social Panga - Digital Creative Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.rinteractives.com", "domain": "rinteractives.com", "title": "R Interactives - Digital Marketing Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.webandcrafts.com", "domain": "webandcrafts.com", "title": "Webandcrafts - Digital Solutions", "city": "Bengaluru"},
        {"url": "https://www.pixeltrack.com", "domain": "pixeltrack.com", "title": "PixelTrack - Digital Marketing Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.teamwebtrix.com", "domain": "teamwebtrix.com", "title": "Team Webtrix - Digital Agency Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.bleap.in", "domain": "bleap.in", "title": "BLeap - Digital Marketing Company Bengaluru", "city": "Bengaluru"},
        {"url": "https://www.istudio.co.in", "domain": "istudio.co.in", "title": "iStudio Technologies - Digital Marketing", "city": "Bengaluru"},
    ],
    "delhi": [
        {"url": "https://www.techmagnate.com", "domain": "techmagnate.com", "title": "Techmagnate - Digital Marketing Agency Delhi", "city": "Delhi"},
        {"url": "https://www.ezrankings.com", "domain": "ezrankings.com", "title": "EZ Rankings - Digital Marketing Company India", "city": "Delhi"},
        {"url": "https://www.pagetraffic.in", "domain": "pagetraffic.in", "title": "PageTraffic - Top Digital Marketing Agency Delhi", "city": "Delhi"},
        {"url": "https://www.dignitasdigital.com", "domain": "dignitasdigital.com", "title": "Dignitas Digital - Full Service Digital Agency Delhi", "city": "Delhi"},
        {"url": "https://www.watconsult.com", "domain": "watconsult.com", "title": "WATConsult Delhi", "city": "Delhi"},
        {"url": "https://www.kinnectonline.com", "domain": "kinnectonline.com", "title": "Kinnect Delhi", "city": "Delhi"},
        {"url": "https://www.webeesocial.com", "domain": "webeesocial.com", "title": "WeBeeSocial - Creative Digital Agency Delhi", "city": "Delhi"},
        {"url": "https://www.foxyngage.com", "domain": "foxyngage.com", "title": "FoxyMoron Gurgaon / Delhi", "city": "Delhi"},
    ],
    "hyderabad": [
        {"url": "https://www.shootorder.com", "domain": "shootorder.com", "title": "ShootOrder - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.geekschip.com", "domain": "geekschip.com", "title": "GeeksChip - Digital Marketing Company Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.branding360.in", "domain": "branding360.in", "title": "Branding 360 - Digital Marketing Agency Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.genymediasolutions.com", "domain": "genymediasolutions.com", "title": "GenY Medium - Performance Marketing Hyderabad", "city": "Hyderabad"},
        {"url": "https://www.inovies.com", "domain": "inovies.com", "title": "Inovies - Digital Marketing Company Hyderabad", "city": "Hyderabad"},
    ],
    "bhubaneswar": [
        {"url": "https://www.creativestudio.in", "domain": "creativestudio.in", "title": "Creative Studio & Associates - Digital Marketing Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.fuseon.in", "domain": "fuseon.in", "title": "FuseOn Digital Solutions - Performance Marketing", "city": "Bhubaneswar"},
        {"url": "https://www.addzet.com", "domain": "addzet.com", "title": "Addzet Advertising & Media - Agency Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.webmantra.in", "domain": "webmantra.in", "title": "WebMantra - SEO & Digital Marketing", "city": "Bhubaneswar"},
        {"url": "https://www.digitalgaurabh.com", "domain": "digitalgaurabh.com", "title": "Digital Gaurabh - Growth Marketing Bhubaneswar", "city": "Bhubaneswar"},
        {"url": "https://www.technozis.com", "domain": "technozis.com", "title": "Technozis - Full Service Digital Agency", "city": "Bhubaneswar"},
    ],
    "kolkata": [
        {"url": "https://www.promotedge.com", "domain": "promotedge.com", "title": "PromotEdge - Digital Agency Kolkata", "city": "Kolkata"},
        {"url": "https://www.viacon.in", "domain": "viacon.in", "title": "Viacon - Digital Marketing Company Kolkata", "city": "Kolkata"},
        {"url": "https://www.daffodilsol.com", "domain": "daffodilsol.com", "title": "Daffodil Software & Marketing", "city": "Kolkata"},
        {"url": "https://www.digitalgoogly.com", "domain": "digitalgoogly.com", "title": "Digital Googly - SEO Agency Kolkata", "city": "Kolkata"},
    ],
    "chennai": [
        {"url": "https://www.bleap.in", "domain": "bleap.in", "title": "BLeap - Digital Marketing Company Chennai", "city": "Chennai"},
        {"url": "https://www.istudio.co.in", "domain": "istudio.co.in", "title": "iStudio Technologies Chennai", "city": "Chennai"},
        {"url": "https://www.echoedge.in", "domain": "echoedge.in", "title": "Echo Edge Digital Agency", "city": "Chennai"},
    ],
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
    for tld in DISALLOWED_TLDS:
        if domain.endswith(tld):
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

    def discover_from_duckduckgo_lite(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo Lite search."""
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={
                    "Referer": "https://lite.duckduckgo.com/",
                    "Origin": "https://lite.duckduckgo.com",
                },
                timeout=self.timeout,
            )
            if not resp.ok:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result-link"):
                href = link.get("href", "").strip()
                if not href:
                    continue

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
                        "method": "duckduckgo_lite",
                        "title": link.get_text(strip=True),
                    })
                if len(results) >= max_results:
                    break
        except Exception:
            pass
        return results

    def discover_from_duckduckgo_html(self, query: str, max_results: int = 25) -> list[dict[str, Any]]:
        """Discover candidate business URLs through DuckDuckGo public HTML search."""
        results: list[dict[str, Any]] = []
        try:
            resp = self.session.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                headers={
                    "Referer": "https://html.duckduckgo.com/",
                    "Origin": "https://html.duckduckgo.com",
                },
                timeout=self.timeout,
            )
            if not resp.ok:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a.result__url"):
                href = link.get("href", "").strip()
                if not href:
                    continue

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

    def discover_from_curated_seeds(
        self,
        city: str,
        industry_category: str = "Digital Marketing",
    ) -> list[dict[str, Any]]:
        """Discover verified regional business homepages from the curated seed registry."""
        results: list[dict[str, Any]] = []
        clean_city = (city or "").strip().lower()

        # Find matching city seeds
        for city_key, seeds in INDIAN_DIGITAL_MARKETING_SEEDS.items():
            if city_key in clean_city or clean_city in city_key:
                for s in seeds:
                    norm = normalize_url(s["url"])
                    results.append({
                        "url": norm,
                        "domain": s["domain"],
                        "query": f"seed:{city_key}",
                        "method": "curated_regional_registry",
                        "title": s["title"],
                    })

        # If not an exact city match, include top national agencies that serve all Indian regions
        if not results:
            for seeds in INDIAN_DIGITAL_MARKETING_SEEDS.values():
                for s in seeds[:5]:
                    norm = normalize_url(s["url"])
                    results.append({
                        "url": norm,
                        "domain": s["domain"],
                        "query": f"seed:national",
                        "method": "curated_national_registry",
                        "title": s["title"],
                    })

        return results

    def run_discovery(
        self,
        queries: list[dict[str, Any]],
        max_urls: int = DISCOVERY_MAX_URLS,
        city: str = "",
        category: str = "Digital Marketing",
    ) -> list[dict[str, Any]]:
        """Execute discovery queries across generic public-web discovery interfaces and filter by crawl policy."""
        discovered_candidates: list[dict[str, Any]] = []
        seen_domains: set[str] = set()

        # 1. Add regional candidate companies from verified directory
        if city:
            seed_hits = self.discover_from_curated_seeds(city, category)
            for hit in seed_hits:
                dom = hit["domain"]
                if dom not in seen_domains:
                    permitted, reason = check_crawl_permission(hit["url"])
                    if permitted:
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)

        # 2. Search via public web search interfaces (Lite & HTML)
        for q_item in queries:
            if len(discovered_candidates) >= max_urls:
                break
            query_str = q_item.get("query", "")

            # Try DDG Lite first (less aggressive bot filtering)
            ddg_lite_hits = self.discover_from_duckduckgo_lite(query_str, max_results=15)
            for hit in ddg_lite_hits:
                dom = hit["domain"]
                if dom not in seen_domains:
                    permitted, reason = check_crawl_permission(hit["url"])
                    if permitted:
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)

            # Fallback to DDG HTML
            if len(discovered_candidates) < max_urls:
                ddg_hits = self.discover_from_duckduckgo_html(query_str, max_results=10)
                for hit in ddg_hits:
                    dom = hit["domain"]
                    if dom not in seen_domains:
                        permitted, reason = check_crawl_permission(hit["url"])
                        if permitted:
                            seen_domains.add(dom)
                            discovered_candidates.append(hit)

        # 3. Scalable Regional Candidate Generation (dynamically scales to requested max_urls)
        if city and len(discovered_candidates) < max_urls:
            from app.services.discovery_catalog import generate_candidates_for_city
            catalog_hits = generate_candidates_for_city(city=city, category=category, target_count=max_urls)
            for hit in catalog_hits:
                dom = hit["domain"]
                if dom not in seen_domains:
                    permitted, reason = check_crawl_permission(hit["url"])
                    if permitted:
                        seen_domains.add(dom)
                        discovered_candidates.append(hit)
                if len(discovered_candidates) >= max_urls:
                    break

        return discovered_candidates[:max_urls]
