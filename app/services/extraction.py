"""Stage 7: Public business data extraction without fabrication (AI + Regex fallback)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit
from pydantic import BaseModel, Field, field_validator
import requests

from app.config import (
    AI_EXTRACTION_TIMEOUT_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
)
from app.services.dedupe import normalize_name

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|@)\s*([A-Za-z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([A-Za-z]{2,}(?:\.[A-Za-z]{2,})?)\b",
    re.I,
)
PHONE_RE = re.compile(
    r"(?:(?:\+|0{0,2})91[\s.-]?)?(?:[6-9]\d{4}[\s.-]?\d{5}|[6-9]\d{2}[\s.-]?\d{3}[\s.-]?\d{4}|[6-9]\d{9}|(?:0?[1-8]\d{1,3})[\s.-]?\d{6,8}|1800[\s.-]?\d{3}[\s.-]?\d{3,4})\b"
)
FOUNDED_RE = re.compile(r"\b(?:founded|established|est\.?|since)\s+(?:in\s+)?(19\d{2}|20[0-2]\d)\b", re.I)
COPYRIGHT_YEAR_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:19\d{2}|20[0-2]\d\s*[-–—]\s*)?(19\d{2}|20[0-2]\d)", re.I)
TEAM_SIZE_RE = re.compile(r"\b([1-9][0-9]{0,3}\+?\s*(?:employees|professionals|team members|specialists))\b", re.I)
LEADERSHIP_ROLES = re.compile(r"\b(founder|co-founder|ceo|managing director|director|principal)\b", re.I)

IGNORED_EMAIL_DOMAINS = {
    "example.com", "domain.com", "yourdomain.com", "sentry.io",
    "wixpress.com", "wordpress.org", "schema.org", "bootstrap.com",
}
IGNORED_EMAIL_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".css", ".js",
}


class ExtractedBusinessProfile(BaseModel):
    """Structured output schema for AI-powered business data extraction."""

    official_business_name: str = Field(
        default="",
        description="Official brand or registered name of the business",
    )
    decision_makers: list[dict[str, str]] = Field(
        default_factory=list,
        description="Names and roles of founders/CEOs/directors (e.g. [{'name': '...', 'role': '...'}])",
    )
    direct_phones: list[str] = Field(
        default_factory=list,
        description="Normalized E.164 +91 Indian contact numbers",
    )
    verified_emails: list[str] = Field(
        default_factory=list,
        description="Legitimate corporate email addresses",
    )
    year_founded: Optional[int] = Field(
        default=None,
        description="Year the company was established (not copyright year)",
    )
    team_size_bracket: str = Field(
        default="unknown",
        description="E.g., 1-10, 11-50, 51-200, 200+, or unknown",
    )
    primary_services: list[str] = Field(
        default_factory=list,
        description="Core offerings e.g. Performance Marketing, SEO",
    )
    physical_address: Optional[dict[str, str]] = Field(
        default=None,
        description="City, State, Locality, 6-digit PIN, full_address",
    )

    @field_validator("official_business_name", "team_size_bracket", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("direct_phones", "verified_emails", "primary_services", mode="before")
    @classmethod
    def _coerce_str_list(cls, v: Any) -> list[str]:
        if not v or not isinstance(v, list):
            return []
        return [str(item).strip() for item in v if item and str(item).strip()]

    @field_validator("decision_makers", mode="before")
    @classmethod
    def _coerce_decision_makers(cls, v: Any) -> list[dict[str, str]]:
        if not v or not isinstance(v, list):
            return []
        cleaned: list[dict[str, str]] = []
        for item in v:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                role = str(item.get("role") or item.get("title") or "").strip()
                if name:
                    cleaned.append({"name": name, "role": role})
        return cleaned

    @field_validator("year_founded", mode="before")
    @classmethod
    def _coerce_year(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or isinstance(v, bool):
            return None
        try:
            yr = int(str(v).strip())
            current_yr = datetime.now(timezone.utc).year
            if 1850 <= yr <= current_yr:
                return yr
        except (ValueError, TypeError):
            pass
        return None

    @field_validator("physical_address", mode="before")
    @classmethod
    def _coerce_address(cls, v: Any) -> Optional[dict[str, str]]:
        if not v or not isinstance(v, dict):
            return None
        return {str(k): str(val).strip() for k, val in v.items() if val is not None and str(val).strip()}


def normalize_indian_phone(value: str) -> str:
    """Normalize valid Indian mobile, landline with STD, or toll-free number to standard format."""
    if not value:
        return ""
    raw = str(value).strip()
    digits = re.sub(r"\D", "", raw)

    # Handle +91 followed by trunk prefix 0 (e.g. +91 022 26834100 or +91 09876543210)
    if digits.startswith("910") and len(digits) in (12, 13):
        digits = "91" + digits[3:]

    # Toll-free numbers: 1800-XXX-XXXX / 1860-XXX-XXXX
    if digits.startswith("91") and len(digits) >= 12 and digits[2:6] in ("1800", "1860"):
        return "+" + digits[:13]
    if digits.startswith(("1800", "1860")) and len(digits) in (10, 11):
        return f"+91{digits}" if not digits.startswith("91") else f"+{digits}"

    # Strip single leading zero from STD / mobile (e.g. 09812345678 or 02226834100 or 06742541234)
    if len(digits) in (11, 12) and digits.startswith("0"):
        digits = digits[1:]

    # +91 followed by 10 digits: mobile (starts with 6-9) or landline (starts with 1-8 except 0)
    if len(digits) == 12 and digits.startswith("91"):
        if digits[2] != "0":
            return "+" + digits

    # 10 digits starting with 1-9 (mobile or 10-digit STD landline)
    if len(digits) == 10 and digits[0] != "0":
        return "+91" + digits

    # STD landlines with 11 digits starting with 91 (e.g. 91 + 2-digit STD + 7-digit local)
    if len(digits) == 11 and digits.startswith("91") and digits[2] != "0":
        return "+" + digits

    return ""


def _extract_company_name(root_url: str, crawled_pages: list[dict[str, Any]]) -> str:
    """Extract official company name from profile cache, metadata, or title tags."""
    # 0. Check discovery candidate profile cache if registered
    from app.services.discovery_catalog import get_candidate_profile
    prof = get_candidate_profile(root_url)
    if prof and prof.get("company_name"):
        return normalize_name(prof["company_name"])

    if not crawled_pages:
        dom = urlsplit(root_url).netloc.replace("www.", "").split(".")[0]
        return dom.capitalize()

    home_page = crawled_pages[0]
    soup: Any = home_page.get("soup")

    if soup:
        # 1. OpenGraph site name
        og_name = soup.find("meta", property="og:site_name")
        if og_name and og_name.get("content"):
            name = og_name["content"].strip()
            if len(name) < 50:
                return normalize_name(name)

        # 2. Schema.org Organization name
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") in ("Organization", "LocalBusiness"):
                    if data.get("name"):
                        return normalize_name(str(data["name"]))
            except Exception:
                pass

    # 3. Clean Title tag (works whether soup is present or not)
    raw_title = home_page.get("title", "")
    if raw_title:
        clean_part = re.split(r"[-|:–—]", raw_title)[0].strip()
        if 2 < len(clean_part) < 60:
            return normalize_name(clean_part)

    dom = urlsplit(root_url).netloc.replace("www.", "").split(".")[0]
    return dom.replace("-", " ").capitalize()


def _deobfuscate_and_clean_email(raw_value: str) -> str:
    """Normalize obfuscated email strings (e.g., 'info [at] company [dot] com') and validate."""
    if not raw_value:
        return ""
    cleaned = unquote(str(raw_value)).split("?")[0].strip()
    cleaned = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*@\s*", "@", cleaned)
    cleaned = re.sub(r"\s*\.\s*", ".", cleaned)
    cleaned = cleaned.strip().lower()

    if not EMAIL_RE.fullmatch(cleaned):
        return ""
    if any(cleaned.endswith(ext) for ext in IGNORED_EMAIL_EXTENSIONS):
        return ""
    domain_part = cleaned.split("@", 1)[-1]
    if any(domain_part == dom or domain_part.endswith("." + dom) for dom in IGNORED_EMAIL_DOMAINS):
        return ""
    return cleaned


def _is_copyright_only_year(year: int, text: str) -> bool:
    """Return True if the given year only appears in copyright notices (e.g. '© 2026') and not founding text."""
    yr_str = str(year)
    if yr_str not in text:
        return False
    if FOUNDED_RE.search(text):
        return False
    # Check if every occurrence of yr_str is preceded by copyright / ©
    occurrences = [m.start() for m in re.finditer(rf"\b{re.escape(yr_str)}\b", text)]
    if not occurrences:
        return False
    for pos in occurrences:
        prefix = text[max(0, pos - 30) : pos].lower()
        if not any(tok in prefix for tok in ("©", "&copy;", "copyright", "all rights reserved")):
            return False
    return True


def _extract_with_ai(
    root_url: str,
    crawled_pages: list[dict[str, Any]],
) -> Optional[ExtractedBusinessProfile]:
    """Extract structured business profile from crawled pages using Gemini Flash."""
    api_key = (os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY).strip()
    if not api_key or not crawled_pages:
        return None

    # Skip external AI call for synthetic regional catalog profiles
    from app.services.discovery_catalog import get_candidate_profile
    if get_candidate_profile(root_url):
        return None

    # Build a compact multi-page digest including HTML contact links
    digest_parts: list[str] = [f"ROOT_URL: {root_url}"]
    all_raw_text = ""

    for page in crawled_pages[:5]:
        p_url = page.get("url", root_url)
        p_type = page.get("page_type", "page")
        p_title = page.get("title", "")
        p_text = page.get("text", "")
        all_raw_text += " " + p_text

        links_found: list[str] = []
        soup: Any = page.get("soup")
        if soup:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if href.lower().startswith(("tel:", "mailto:")) or "wa.me/" in href or "whatsapp.com" in href:
                    links_found.append(href)

        section = f"\n--- PAGE ({p_type}): {p_url} | TITLE: {p_title} ---\n"
        if links_found:
            section += "LINKS: " + ", ".join(links_found[:15]) + "\n"
        section += p_text[:3000]
        digest_parts.append(section)

    website_content = "\n".join(digest_parts)[:12000]
    if len(all_raw_text.strip()) < 10 and "LINKS:" not in website_content:
        return None

    prompt = (
        "You are an expert B2B business data extractor. Extract factual business information "
        "strictly from the provided website content into the requested JSON structure.\n"
        "CRITICAL RULES:\n"
        "1. Zero Fabrication: Never invent or guess any data. Use empty lists/strings or null if missing.\n"
        "2. Obfuscated Emails: Convert disguised emails like 'info [at] company [dot] com' into 'info@company.com'.\n"
        "3. Phone Numbers & WhatsApp: Extract business contact numbers from text, tel: links, and WhatsApp links "
        "(e.g. https://wa.me/919876543210) and normalize Indian numbers to +91XXXXXXXXXX.\n"
        "4. Leadership / Decision Makers: Extract ONLY actual founders, CEOs, or directors of THIS company. "
        "Do NOT extract famous people mentioned as inspiration (e.g. 'Our founder was inspired by Steve Jobs') "
        "or external clients from testimonials.\n"
        "5. Year Founded: Extract ONLY the year the company was established. Do NOT use footer copyright dates (e.g. '© 2026').\n\n"
        "Return ONLY valid JSON matching these keys:\n"
        "{\n"
        '  "official_business_name": "string",\n'
        '  "decision_makers": [{"name": "string", "role": "string"}],\n'
        '  "direct_phones": ["string"],\n'
        '  "verified_emails": ["string"],\n'
        '  "year_founded": integer or null,\n'
        '  "team_size_bracket": "string",\n'
        '  "primary_services": ["string"],\n'
        '  "physical_address": {"city": "string", "state": "string", "locality": "string", "pin": "string"} or null\n'
        "}\n\n"
        f"WEBSITE CONTENT:\n{website_content}"
    )

    model_name = (os.getenv("GEMINI_MODEL", "") or GEMINI_MODEL or "gemini-2.0-flash").strip()
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    try:
        resp = requests.post(
            endpoint,
            params={"key": api_key},
            json=payload,
            timeout=AI_EXTRACTION_TIMEOUT_SECONDS,
        )
        if not resp.ok:
            return None

        resp_json = resp.json()
        raw_text = (
            resp_json.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        ).strip()
        if not raw_text:
            return None

        # Strip optional markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.I | re.S).strip()

        profile = ExtractedBusinessProfile.model_validate_json(raw_text)

        # Normalize and validate extracted phones and emails
        valid_phones: list[str] = []
        for ph in profile.direct_phones:
            norm_ph = normalize_indian_phone(ph)
            if norm_ph and norm_ph not in valid_phones:
                valid_phones.append(norm_ph)
        profile.direct_phones = valid_phones

        valid_emails: list[str] = []
        for em in profile.verified_emails:
            clean_em = _deobfuscate_and_clean_email(em)
            if clean_em and clean_em not in valid_emails:
                valid_emails.append(clean_em)
        profile.verified_emails = valid_emails

        # Guard against copyright year false positives
        if profile.year_founded and _is_copyright_only_year(profile.year_founded, all_raw_text):
            profile.year_founded = None

        return profile
    except Exception:
        return None


def extract_business_data(
    root_url: str,
    crawled_pages: list[dict[str, Any]],
    industry_category: str = "Digital Marketing",
    city: str = "",
    state: str = "",
    country: str = "India",
    locality: str = "",
) -> dict[str, Any]:
    """Extract verifiable business information from crawled pages without fabrication."""
    now = datetime.now(timezone.utc).isoformat()
    evidence_items: list[dict[str, Any]] = []

    company_name = _extract_company_name(root_url, crawled_pages)
    evidence_items.append({
        "field_name": "company_name",
        "field_value": company_name,
        "source_url": root_url,
        "evidence_excerpt": f"Company identity established from {root_url}",
        "verification_status": "verified",
    })

    phone = ""
    email = ""
    contact_person = ""
    contact_role = ""
    company_size = "unknown"
    company_age = "unknown"
    services: list[str] = []

    # 0. Attempt AI-powered structured extraction first (falls back to Regex if unavailable)
    ai_profile = _extract_with_ai(root_url, crawled_pages)
    if ai_profile is not None:
        if ai_profile.official_business_name:
            company_name = ai_profile.official_business_name
            evidence_items[0]["field_value"] = company_name
            evidence_items[0]["evidence_excerpt"] = f"AI extracted official business name: {company_name}"

        if ai_profile.direct_phones:
            phone = ai_profile.direct_phones[0]
            evidence_items.append({
                "field_name": "phone",
                "field_value": phone,
                "source_url": root_url,
                "evidence_excerpt": f"AI extracted verified phone: {phone}",
                "verification_status": "verified",
            })

        if ai_profile.verified_emails:
            email = ai_profile.verified_emails[0]
            evidence_items.append({
                "field_name": "email",
                "field_value": email,
                "source_url": root_url,
                "evidence_excerpt": f"AI extracted verified email: {email}",
                "verification_status": "verified",
            })

        if ai_profile.decision_makers:
            dm = ai_profile.decision_makers[0]
            contact_person = dm.get("name", "")
            contact_role = dm.get("role", "")
            if contact_person:
                evidence_items.append({
                    "field_name": "contact_person",
                    "field_value": f"{contact_person} ({contact_role})" if contact_role else contact_person,
                    "source_url": root_url,
                    "evidence_excerpt": f"AI extracted leadership: {contact_person} ({contact_role})",
                    "verification_status": "verified",
                })

        if ai_profile.year_founded:
            company_age = f"Founded {ai_profile.year_founded}"
            evidence_items.append({
                "field_name": "company_age",
                "field_value": company_age,
                "source_url": root_url,
                "evidence_excerpt": f"AI extracted establishment year: {ai_profile.year_founded}",
                "verification_status": "verified",
            })

        if ai_profile.team_size_bracket and ai_profile.team_size_bracket.lower() != "unknown":
            company_size = ai_profile.team_size_bracket
            evidence_items.append({
                "field_name": "company_size",
                "field_value": company_size,
                "source_url": root_url,
                "evidence_excerpt": f"AI extracted team size: {company_size}",
                "verification_status": "verified",
            })

        if ai_profile.primary_services:
            services = ai_profile.primary_services[:8]

        if ai_profile.physical_address:
            addr = ai_profile.physical_address
            if not locality and addr.get("locality"):
                locality = addr["locality"]
            if not city and addr.get("city"):
                city = addr["city"]
            if not state and addr.get("state"):
                state = addr["state"]
            addr_summary = ", ".join(v for v in addr.values() if v)
            if addr_summary:
                evidence_items.append({
                    "field_name": "physical_address",
                    "field_value": addr_summary,
                    "source_url": root_url,
                    "evidence_excerpt": f"AI extracted address: {addr_summary}",
                    "verification_status": "verified",
                })

    all_text = " ".join(p.get("text", "") for p in crawled_pages)

    # 1. Inspect links and page content for contact information (Regex/DOM fallback & supplement)
    for page in crawled_pages:
        soup: Any = page.get("soup")
        p_url = page.get("url", root_url)
        if not soup:
            continue

        # Check tel: links (highest accuracy)
        if not phone:
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if href.lower().startswith("tel:"):
                    norm = normalize_indian_phone(unquote(href[4:]))
                    if norm:
                        phone = norm
                        evidence_items.append({
                            "field_name": "phone",
                            "field_value": phone,
                            "source_url": p_url,
                            "evidence_excerpt": f"Published tel link: {href}",
                            "verification_status": "verified",
                        })
                        break

        # Check WhatsApp direct chat links (widely used by Indian businesses)
        if not phone:
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if "wa.me/" in href or "api.whatsapp.com/send" in href or "web.whatsapp.com/send" in href:
                    wa_phone = ""
                    if "phone=" in href:
                        try:
                            wa_phone = parse_qs(urlsplit(href).query).get("phone", [""])[0]
                        except Exception:
                            pass
                    if not wa_phone and "wa.me/" in href:
                        wa_phone = href.split("wa.me/")[-1].split("?")[0].split("/")[0]
                    norm = normalize_indian_phone(wa_phone)
                    if norm:
                        phone = norm
                        evidence_items.append({
                            "field_name": "phone",
                            "field_value": phone,
                            "source_url": p_url,
                            "evidence_excerpt": f"Published WhatsApp direct chat link: {href}",
                            "verification_status": "verified",
                        })
                        break

        # Check Schema.org / JSON-LD telephone metadata
        if not phone:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    raw_data = json.loads(script.string or "")
                    items = [raw_data] if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])
                    for it in items:
                        if isinstance(it, dict):
                            tel = it.get("telephone")
                            if not tel and isinstance(it.get("contactPoint"), dict):
                                tel = it["contactPoint"].get("telephone")
                            if tel:
                                norm = normalize_indian_phone(str(tel))
                                if norm:
                                    phone = norm
                                    evidence_items.append({
                                        "field_name": "phone",
                                        "field_value": phone,
                                        "source_url": p_url,
                                        "evidence_excerpt": f"Schema.org telephone metadata: {tel}",
                                        "verification_status": "verified",
                                    })
                                    break
                    if phone:
                        break
                except Exception:
                    pass

        # Check HTML microdata itemprop="telephone"
        if not phone:
            el = soup.find(attrs={"itemprop": "telephone"})
            if el:
                tel_text = el.get_text(strip=True) or el.get("content", "")
                norm = normalize_indian_phone(tel_text)
                if norm:
                    phone = norm
                    evidence_items.append({
                        "field_name": "phone",
                        "field_value": phone,
                        "source_url": p_url,
                        "evidence_excerpt": f"Microdata itemprop telephone: {tel_text}",
                        "verification_status": "verified",
                    })

        # Check mailto: links (highest accuracy)
        if not email:
            for link in soup.find_all("a", href=True):
                href = link["href"].strip()
                if href.lower().startswith("mailto:"):
                    raw_email = _deobfuscate_and_clean_email(href[7:])
                    if raw_email:
                        email = raw_email
                        evidence_items.append({
                            "field_name": "email",
                            "field_value": email,
                            "source_url": p_url,
                            "evidence_excerpt": f"Published mailto link: {raw_email}",
                            "verification_status": "verified",
                        })
                        break

    # 1B. Check WhatsApp URLs embedded directly in plain text
    if not phone:
        wa_text_match = re.search(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\+?91?\d{10,12})", all_text, re.I)
        if wa_text_match:
            norm = normalize_indian_phone(wa_text_match.group(1))
            if norm:
                phone = norm
                evidence_items.append({
                    "field_name": "phone",
                    "field_value": phone,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published WhatsApp link in text: {wa_text_match.group(0)}",
                    "verification_status": "verified",
                })

    # 2. Extract from explicit phone/contact labels in page text
    if not phone:
        LABEL_PHONE_RE = re.compile(
            r"(?:phone|tel|mobile|call(?:\s+us)?|contact(?:\s+no\.?)?|helpline|reach\s+us\s+at)\s*[:–-]?\s*([+0-9\s()./-]{8,25})",
            re.I,
        )
        for m in LABEL_PHONE_RE.finditer(all_text):
            norm = normalize_indian_phone(m.group(1))
            if norm:
                phone = norm
                evidence_items.append({
                    "field_name": "phone",
                    "field_value": phone,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published contact label in page: {m.group(0).strip()}",
                    "verification_status": "verified",
                })
                break

    # 3. Fallback: Extract from text via phone regex
    if not phone:
        for ph in PHONE_RE.findall(all_text):
            norm = normalize_indian_phone(ph)
            if norm:
                phone = norm
                evidence_items.append({
                    "field_name": "phone",
                    "field_value": phone,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published phone found in page body: {ph}",
                    "verification_status": "verified",
                })
                break

    if not email:
        for em in EMAIL_RE.findall(all_text):
            clean_em = _deobfuscate_and_clean_email(em)
            if clean_em:
                email = clean_em
                evidence_items.append({
                    "field_name": "email",
                    "field_value": email,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published email in page text: {em}",
                    "verification_status": "verified",
                })
                break

    # 3B. Fallback: Obfuscated email in page text (e.g. info [at] company [dot] com)
    if not email:
        for m in OBFUSCATED_EMAIL_RE.finditer(all_text):
            candidate = f"{m.group(1)}@{m.group(2)}.{m.group(3)}"
            clean_em = _deobfuscate_and_clean_email(candidate)
            if clean_em:
                email = clean_em
                evidence_items.append({
                    "field_name": "email",
                    "field_value": email,
                    "source_url": root_url,
                    "evidence_excerpt": f"Published obfuscated email in page text: {m.group(0)}",
                    "verification_status": "verified",
                })
                break

    # 4. Extract company age / founding year (excluding copyright years)
    if company_age == "unknown":
        found_match = FOUNDED_RE.search(all_text)
        if found_match:
            year = int(found_match.group(1))
            if not _is_copyright_only_year(year, all_text):
                company_age = f"Founded {year}"
                evidence_items.append({
                    "field_name": "company_age",
                    "field_value": company_age,
                    "source_url": root_url,
                    "evidence_excerpt": found_match.group(0),
                    "verification_status": "verified",
                })

    # 5. Extract company size / team size
    if company_size == "unknown":
        team_match = TEAM_SIZE_RE.search(all_text)
        if team_match:
            company_size = team_match.group(1)
            evidence_items.append({
                "field_name": "company_size",
                "field_value": company_size,
                "source_url": root_url,
                "evidence_excerpt": team_match.group(0),
                "verification_status": "verified",
            })

    # 6. Extract publicly listed leadership / contact person from About/Team pages
    if not contact_person:
        about_pages = [p for p in crawled_pages if p.get("page_type") in ("about", "contact")]
        for p in about_pages:
            txt = p.get("text", "")
            for role_match in LEADERSHIP_ROLES.finditer(txt):
                start = max(0, role_match.start() - 40)
                end = min(len(txt), role_match.end() + 40)
                snippet = txt[start:end]
                # Skip false-positive inspiration mentions like "Our founder was inspired by Steve Jobs"
                if re.search(r"\b(?:inspired\s+by|quoted|like|admire[sd]?)\b", snippet, re.I):
                    continue
                contact_role = role_match.group(1).title()
                name_candidates = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", snippet)
                # Filter out role words themselves or generic phrases from name candidates
                filtered_names = [
                    n for n in name_candidates
                    if not LEADERSHIP_ROLES.search(n)
                    and n.lower() not in ("our founder", "our team", "meet our", "contact us", "about us")
                ]
                if filtered_names:
                    contact_person = filtered_names[0]
                    evidence_items.append({
                        "field_name": "contact_person",
                        "field_value": f"{contact_person} ({contact_role})",
                        "source_url": p.get("url", root_url),
                        "evidence_excerpt": snippet.strip(),
                        "verification_status": "verified",
                    })
                    break
            if contact_person:
                break

    result: dict[str, Any] = {
        "company_name": company_name,
        "industry_category": industry_category,
        "country": country or "India",
        "state": state,
        "city": city,
        "locality": locality,
        "website": root_url,
        "phone": phone,
        "has_phone": bool(phone),
        "email": email,
        "contact_person": contact_person,
        "contact_role": contact_role,
        "company_size": company_size,
        "company_age": company_age,
        "extracted_at": now,
        "evidence_items": evidence_items,
    }
    if services:
        result["services"] = services
    return result
