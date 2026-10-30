"""Indexed deduplication and high-quality lead merging.

Provides O(N) deduplication using normalized hash indexes on:
1. Indian Corporate Identity Number (CIN)
2. Normalized canonical website domains (excluding directory/social hosts)
3. Normalized distinctive company names partitioned by geographic locality

Preserves and merges non-empty attributes, source attributions, and evidence
rather than discarding matching records.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

GENERIC_NAME_TERMS = {
    "digital",
    "marketing",
    "digitalmarketing",
    "advertising",
    "media",
    "creative",
    "creatives",
    "agency",
    "solutions",
    "services",
    "technologies",
    "tech",
    "studio",
    "group",
    "enterprises",
    "infotech",
    "online",
    "global",
    "india",
}

NON_COMPANY_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "pinterest.com",
    "wikipedia.org",
    "reddit.com",
    "justdial.com",
    "sulekha.com",
    "indiamart.com",
    "tradeindia.com",
    "clutch.co",
    "goodfirms.co",
    "sortlist.com",
    "ambitionbox.com",
    "glassdoor.com",
    "indeed.com",
    "naukri.com",
    "google.com",
    "maps.google.com",
    "bing.com",
    "yelp.com",
    "yellowpages.com",
    "crunchbase.com",
    "github.com",
    "medium.com",
}


def domain(value: str) -> str:
    """Extract canonical domain without www, port or path.

    Rejects common social, directory, and invalid hostnames.
    """
    if not value:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw

    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        host = host.removeprefix("www.")

        if not host or "." not in host:
            return ""

        # Check if domain belongs to a generic/directory site
        for blocked in NON_COMPANY_DOMAINS:
            if host == blocked or host.endswith("." + blocked):
                return ""

        return host
    except Exception:
        return ""


def normalize_name(value: str, city: str = "") -> str:
    """Normalize company name by stripping legal suffixes, city context, and punctuation."""
    if not value:
        return ""

    clean = str(value).casefold()

    # Remove legal suffixes
    clean = re.sub(
        r"\b(pvt|private|ltd|limited|llp|llc|inc|corp|corporation|co|holdings|group)\b",
        " ",
        clean,
    )

    # Remove city if appended as a location suffix
    if city:
        clean_city = str(city).casefold().strip()
        if len(clean_city) >= 3:
            clean = re.sub(rf"\b{re.escape(clean_city)}\b", " ", clean)

    # Remove non-alphanumeric
    clean = re.sub(r"[^a-z0-9]", "", clean)
    return clean.strip()


def normalize_cin(value: Any) -> str:
    """Normalize Indian Corporate Identity Number (21 chars alphanumeric)."""
    if not value:
        return ""
    digits_alpha = re.sub(r"[^a-zA-Z0-9]", "", str(value)).upper()
    if len(digits_alpha) == 21:
        return digits_alpha
    return ""


def normalize_city(value: Any) -> str:
    """Normalize city name for grouping."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def merge_record(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge non-empty fields from incoming record into target in place."""
    # Simple scalar fields
    for field_name in (
        "website",
        "phone",
        "email",
        "city",
        "state",
        "address",
        "category",
        "sector",
        "cin",
        "company_status",
        "registration_date",
        "company_age_years",
    ):
        target_val = target.get(field_name)
        incoming_val = incoming.get(field_name)

        if not target_val and incoming_val:
            target[field_name] = incoming_val
        elif field_name == "address" and target_val and incoming_val:
            # Prefer longer address if incoming is noticeably more detailed
            if len(str(incoming_val)) > len(str(target_val)) + 10:
                target["address"] = incoming_val
        elif field_name == "website" and incoming_val:
            # If target website is HTTP and incoming is HTTPS
            if str(target_val).startswith("http://") and str(incoming_val).startswith("https://"):
                target["website"] = incoming_val

    # Merge sources
    target_sources = set(
        s.strip() for s in str(target.get("source", "")).split(";") if s.strip()
    )
    incoming_sources = set(
        s.strip() for s in str(incoming.get("source", "")).split(";") if s.strip()
    )
    target["source"] = "; ".join(sorted(target_sources | incoming_sources))

    # Evidence lists
    target_ev = target.get("evidence", [])
    if isinstance(target_ev, list):
        incoming_ev = incoming.get("evidence", [])
        if isinstance(incoming_ev, list):
            for ev in incoming_ev:
                if ev and ev not in target_ev:
                    target_ev.append(ev)
    elif incoming.get("evidence"):
        target["evidence"] = list(incoming.get("evidence", []))

    # Location verified flag
    target["_location_verified"] = bool(
        target.get("_location_verified") or incoming.get("_location_verified")
    )

    # Combine relevance text up to 4000 characters
    target_rel = str(target.get("_relevance_text", "")).strip()
    incoming_rel = str(incoming.get("_relevance_text", "")).strip()
    if incoming_rel and incoming_rel not in target_rel:
        combined = f"{target_rel} {incoming_rel}".strip()
        target["_relevance_text"] = combined[:4000]

    # Combine score and reason if already evaluated
    if incoming.get("lead_quality_score", 0) > target.get("lead_quality_score", 0):
        target["lead_quality_score"] = incoming["lead_quality_score"]
        if incoming.get("score_reason"):
            target["score_reason"] = incoming["score_reason"]


class IndexedDeduplicator:
    """Hash-indexed lead deduplicator and merger with O(1) matching per record."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._by_cin: dict[str, int] = {}
        self._by_domain: dict[str, int] = {}
        self._by_name_city: dict[tuple[str, str], int] = {}
        self._by_name: dict[str, int] = {}

    def add_or_merge(self, record: dict[str, Any]) -> None:
        incoming = dict(record)
        city_raw = incoming.get("city", "")
        name_key = normalize_name(incoming.get("company_name", ""), city_raw)
        domain_key = domain(incoming.get("website", ""))
        cin_key = normalize_cin(incoming.get("cin", ""))
        city_key = normalize_city(city_raw)

        target_idx: int | None = None

        # 1. Match on CIN (highest confidence legal identifier)
        if cin_key and cin_key in self._by_cin:
            target_idx = self._by_cin[cin_key]

        # 2. Match on unique company domain
        elif domain_key and domain_key in self._by_domain:
            target_idx = self._by_domain[domain_key]

        # 3. Match on (name, city) if name is not purely generic
        elif (
            name_key
            and len(name_key) >= 3
            and name_key not in GENERIC_NAME_TERMS
            and (name_key, city_key) in self._by_name_city
        ):
            target_idx = self._by_name_city[(name_key, city_key)]

        # 4. Match on distinctive name (>= 6 chars) across missing city
        elif (
            name_key
            and len(name_key) >= 6
            and name_key not in GENERIC_NAME_TERMS
            and name_key in self._by_name
        ):
            existing_idx = self._by_name[name_key]
            existing_rec = self.records[existing_idx]
            existing_city = normalize_city(existing_rec.get("city", ""))
            # If one or both cities are unspecified or they match
            if not city_key or not existing_city or city_key == existing_city:
                target_idx = existing_idx

        if target_idx is not None:
            # Merge into existing record
            merge_record(self.records[target_idx], incoming)
            idx = target_idx
            if cin_key and cin_key not in self._by_cin:
                self._by_cin[cin_key] = idx
            if domain_key and domain_key not in self._by_domain:
                self._by_domain[domain_key] = idx
            if name_key and (name_key, city_key) not in self._by_name_city:
                self._by_name_city[(name_key, city_key)] = idx
        else:
            # Add as new record
            idx = len(self.records)
            self.records.append(incoming)
            if cin_key:
                self._by_cin[cin_key] = idx
            if domain_key:
                self._by_domain[domain_key] = idx
            if name_key:
                self._by_name_city[(name_key, city_key)] = idx
                if len(name_key) >= 6 and name_key not in GENERIC_NAME_TERMS:
                    self._by_name.setdefault(name_key, idx)

    def get_results(self) -> list[dict[str, Any]]:
        return self.records


def deduplicate(leads: list[dict]) -> list[dict]:
    """Backward-compatible deduplication function returning merged unique leads."""
    deduper = IndexedDeduplicator()

    # Process leads; higher scored or more detailed leads given earlier priority
    ordered = sorted(
        leads,
        key=lambda x: (
            x.get("lead_quality_score", 0),
            bool(x.get("website")),
            bool(x.get("phone")),
            bool(x.get("email")),
        ),
        reverse=True,
    )

    for lead in ordered:
        deduper.add_or_merge(lead)

    return deduper.get_results()
