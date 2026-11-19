"""Stage 6B: Strict Geographical Location Verification and Evidence Grounding.

Ensures businesses are only verified for a target city if they possess a genuine physical
headquarters or branch office in that city, eliminating cross-city false positives.
"""
from __future__ import annotations

import re
from typing import Any

# Regex to detect 6-digit Indian Postal PIN codes
PIN_CODE_RE = re.compile(r"\b([1-9][0-9]{2}\s?[0-9]{3})\b")

HQ_TERMS = re.compile(r"\b(head office|corporate office|registered office|headquarters|hq|main office|our presence|presence)\b", re.I)
BRANCH_TERMS = re.compile(r"\b(branch office|regional office|our branches|our locations|branch)\b", re.I)
SERVICE_AREA_TERMS = re.compile(r"\b(serving|clients in|services in|service area|work across|delivered in|projects in)\b", re.I)

# Physical address indicators that confirm an actual physical office rather than a passing mention
ADDRESS_INDICATORS = re.compile(
    r"\b(road|street|floor|nagar|park|plot|building|tower|complex|office|sector|suite|block|opp|near|lane|avenue|marg|circle|sq|square|bhavan|bldg|village|bunglows|villa|center|centre)\b",
    re.I,
)

# Known PIN code prefixes for major Indian cities to validate physical address grounding
CITY_PIN_PREFIXES: dict[str, tuple[str, ...]] = {
    "delhi": ("110",),
    "mumbai": ("400", "401"),
    "pune": ("411", "412"),
    "bengaluru": ("560", "561", "562"),
    "bangalore": ("560", "561", "562"),
    "hyderabad": ("500", "501", "502"),
    "chennai": ("600",),
    "kolkata": ("700", "701"),
    "bhubaneswar": ("751", "752"),
    "cuttack": ("753",),
    "rourkela": ("769",),
    "ahmedabad": ("380", "382"),
    "jaipur": ("302",),
    "chandigarh": ("160",),
    "indore": ("452",),
    "kochi": ("682",),
}

CITY_STD_CODES: dict[str, tuple[str, ...]] = {
    "delhi": ("011", "11"),
    "mumbai": ("022", "22"),
    "pune": ("020", "20"),
    "bengaluru": ("080", "80"),
    "bangalore": ("080", "80"),
    "hyderabad": ("040", "40"),
    "chennai": ("044", "44"),
    "kolkata": ("033", "33"),
    "bhubaneswar": ("0674", "674"),
    "ahmedabad": ("079", "79"),
    "jaipur": ("0141", "141"),
}

CITY_KNOWN_LOCALITIES: dict[str, tuple[str, ...]] = {
    "mumbai": (
        "andheri", "bandra", "bkc", "lower parel", "powai", "thane", "navi mumbai", "goregaon",
        "malad", "dadar", "worli", "fort", "juhu", "borivali", "vashi", "nariman point",
        "santacruz", "khar", "kandivali", "mulund", "ghatkopar", "chembur", "vikhroli",
        "kanjurmarg", "bhandup", "wadala", "sion", "matunga", "parel", "mahalaxmi",
        "prabhadevi", "churchgate", "colaba", "marine lines", "byculla", "kurla",
        "sakinaka", "saki naka", "marol", "chakala", "jogeshwari", "lokhandwala",
        "versova", "dahisar", "mira road", "airoli", "belapur", "kharghar", "mahape",
        "turbhe", "sanpada", "kalyan", "dombivli", "vasai", "virar", "kalina", "vakola",
    ),
    "bengaluru": (
        "koramangala", "indiranagar", "hsr layout", "whitefield", "electronic city", "jayanagar",
        "marathahalli", "btm layout", "malleshwaram", "bellandur", "jp nagar", "banashankari",
        "hebbal", "yelahanka", "mg road", "domlur", "kalyan nagar", "sarjapur", "rajajinagar",
    ),
    "delhi": (
        "connaught place", "nehru place", "saket", "okhla", "south extension", "pitampura",
        "janakpuri", "dwarka", "gurgaon", "gurugram", "noida", "rohini", "karol bagh",
        "laxmi nagar", "vasant kunj", "hauz khas", "greater kailash", "rajouri garden", "faridabad",
    ),
    "pune": (
        "kothrud", "hinjewadi", "viman nagar", "baner", "wakad", "koregaon park",
        "shivajinagar", "aundh", "magarpatta", "hadapsar", "kalyani nagar", "pimpri",
        "chinchwad", "kharadi", "bavdhan", "camp", "deccan", "yerawada",
    ),
    "hyderabad": (
        "hitec city", "Madhapur", "gachibowli", "banjara hills", "jubilee hills", "kondapur",
        "begumpet", "secunderabad", "ameerpet", "kukatpally", "somajiguda", "financial district",
    ),
    "bhubaneswar": (
        "saheed nagar", "patia", "nayapalli", "infocity", "chandrasekharpur", "rasulgarh",
        "khandagiri", "jaydev vihar", "mancheswar", "bapuji nagar", "kharvela nagar", "baramunda",
    ),
    "kolkata": (
        "salt lake", "sector v", "park street", "new town", "bidhannagar", "rajarhat",
        "ballygunge", "alipore", "dalhousie", "camac street", "gariahat", "howrah",
    ),
    "chennai": (
        "t nagar", "omr", "guindy", "anna nagar", "velachery", "nungambakkam",
        "adyar", "mylapore", "alwarpet", "porur", "ambattur", "thiruvanmiyur",
    ),
    "ahmedabad": (
        "sg highway", "prahlad nagar", "navrangpura", "bodakdev", "satellite",
        "vastrapur", "ashram road", "maninagar", "thaltej", "cg road", "ellisbridge",
    ),
    "jaipur": (
        "malviya nagar", "vaishali nagar", "mansarovar", "c scheme", "mi road",
        "raja park", "tonk road", "bani park", "jagatpura", "sitapura",
    ),
}


def _extract_windows(page_text: str, clean_city: str, alternate_terms: tuple[str, ...] = ()) -> list[str]:
    """Extract candidate address blocks from both explicit line breaks and contextual text windows."""
    candidates: list[str] = []
    all_terms = [clean_city] + [t for t in alternate_terms if t]
    
    # 1. Line and paragraph blocks
    for line in re.split(r"[\n\r|•;]+", page_text):
        c = line.strip()
        lower_c = c.lower()
        if 10 < len(c) < 400 and any(re.search(r"\b" + re.escape(term) + r"\b", lower_c) for term in all_terms):
            candidates.append(c)

    # 2. Contextual sliding windows around city or locality occurrences
    lower_text = page_text.lower()
    for term in all_terms:
        for m in re.finditer(r"\b" + re.escape(term) + r"\b", lower_text):
            start = max(0, m.start() - 140)
            end = min(len(page_text), m.end() + 200)
            window = page_text[start:end].strip()
            if window and window not in candidates:
                candidates.append(window)

    return candidates


def verify_location(
    city: str,
    state: str,
    country: str,
    locality: str,
    crawled_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify company presence in the target city with strict anti-hallucination grounding."""
    clean_city = (city or "").strip().lower()
    clean_state = (state or "").strip().lower()
    clean_locality = (locality or "").strip().lower()

    if not clean_city:
        return {
            "verified": False,
            "location_type": "unverified",
            "evidence_excerpt": "No city specified for verification",
            "source_url": "",
            "locality": locality,
        }

    # Sort pages: evaluate contact/about pages first for authoritative address data
    sorted_pages = sorted(
        crawled_pages,
        key=lambda p: 0 if p.get("page_type") in ("contact", "about", "locations") else 1,
    )

    detected_type = "unverified"
    best_evidence = ""
    best_url = ""
    matched_locality = locality
    expected_pins = CITY_PIN_PREFIXES.get(clean_city, ())

    for page in sorted_pages:
        page_text = page.get("text", "")
        page_url = page.get("url", "")
        lower_page = page_text.lower()
        page_type = page.get("page_type", "")
        is_contact_page = page_type in ("contact", "about", "locations")

        localities = CITY_KNOWN_LOCALITIES.get(clean_city, ())
        has_locality = any(
            re.search(r"\b" + re.escape(loc.lower()) + r"\b", lower_page)
            for loc in localities
        )
        std_codes = CITY_STD_CODES.get(clean_city, ())
        has_std_phone = any(
            re.search(r"(\+91[\s\-]?)?" + re.escape(code) + r"[\s\-]?[0-9]{6,8}\b", page_text)
            for code in std_codes
        )
        has_city_pin = bool(
            expected_pins
            and any(
                m.group(1).replace(" ", "").startswith(expected_pins)
                for m in PIN_CODE_RE.finditer(page_text)
            )
        )
        is_city_match = (clean_city in lower_page) or has_locality or has_std_phone or has_city_pin

        if not is_city_match:
            continue

        windows = _extract_windows(page_text, clean_city, tuple(loc.lower() for loc in localities))
        if has_city_pin and not windows:
            for m in PIN_CODE_RE.finditer(page_text):
                if m.group(1).replace(" ", "").startswith(expected_pins):
                    start = max(0, m.start() - 140)
                    end = min(len(page_text), m.end() + 100)
                    windows.append(page_text[start:end].strip())
        for w_clean in windows:
            w_lower = w_clean.lower()
            pin_match = PIN_CODE_RE.search(w_clean)
            pin_str = pin_match.group(1).replace(" ", "") if pin_match else ""
            has_address_cues = bool(ADDRESS_INDICATORS.search(w_lower)) or bool(pin_match)

            # If a 6-digit PIN is present in the snippet, verify whether it matches the target city
            if pin_str and expected_pins:
                if not any(pin_str.startswith(exp) for exp in expected_pins):
                    # PIN belongs to another city (e.g. Mumbai 400053 in a Delhi run); do not use as primary proof
                    continue

            # 1. Explicit Branch Office
            if BRANCH_TERMS.search(w_lower) and has_address_cues:
                detected_type = "branch"
                best_evidence = w_clean
                best_url = page_url
                break
            # 2. Explicit Headquarters / Corporate Office
            elif HQ_TERMS.search(w_lower) and has_address_cues:
                detected_type = "headquarters"
                best_evidence = w_clean
                best_url = page_url
                break
            # 3. Contact page with physical address cues and matching PIN
            elif is_contact_page and has_address_cues and pin_str:
                detected_type = "headquarters" if (HQ_TERMS.search(w_lower) or not BRANCH_TERMS.search(w_lower)) else "branch"
                best_evidence = w_clean
                best_url = page_url
                break
            # 4. Explicit Branch / HQ term on contact page
            elif is_contact_page and (BRANCH_TERMS.search(w_lower) or HQ_TERMS.search(w_lower)):
                detected_type = "branch" if BRANCH_TERMS.search(w_lower) else "headquarters"
                best_evidence = w_clean
                best_url = page_url
                break
            # 5. Service area / casual client reference
            elif SERVICE_AREA_TERMS.search(w_lower):
                if detected_type == "unverified":
                    detected_type = "service_area"
                    best_evidence = w_clean
                    best_url = page_url
            # 6. Contact page with address cues (e.g., "N4/2 IRC Village Nayapalli Bhubaneswar")
            elif is_contact_page and has_address_cues and detected_type == "unverified":
                detected_type = "branch" if BRANCH_TERMS.search(w_lower) else "headquarters"
                best_evidence = w_clean
                best_url = page_url
            elif detected_type == "unverified" and not best_evidence:
                best_evidence = w_clean
                best_url = page_url

        # Check for confirmed landline phone with regional STD code
        if has_std_phone and detected_type == "unverified":
            detected_type = "headquarters"
            best_evidence = f"Verified landline phone with regional STD code for {clean_city.title()}"
            best_url = page_url

        if detected_type in ("headquarters", "branch"):
            break

    # Resolve specific commercial locality from evidence or page text
    all_pages_lower = " ".join(p.get("text", "").lower() for p in crawled_pages)
    if clean_locality and re.search(r"\b" + re.escape(clean_locality) + r"\b", all_pages_lower):
        matched_locality = locality
    else:
        matched_locality = ""
        ev_lower = best_evidence.lower()
        for loc in CITY_KNOWN_LOCALITIES.get(clean_city, ()):
            if re.search(r"\b" + re.escape(loc.lower()) + r"\b", ev_lower):
                matched_locality = "BKC" if loc.lower() == "bkc" else loc.title()
                break
        if not matched_locality:
            for loc in CITY_KNOWN_LOCALITIES.get(clean_city, ()):
                if re.search(r"\b" + re.escape(loc.lower()) + r"\b", all_pages_lower):
                    matched_locality = "BKC" if loc.lower() == "bkc" else loc.title()
                    break
        if not matched_locality and locality:
            matched_locality = locality

    # If evidence found without an explicit HQ/Branch marker
    if best_evidence and detected_type == "unverified":
        has_pin = bool(PIN_CODE_RE.search(best_evidence))
        has_cues = bool(ADDRESS_INDICATORS.search(best_evidence.lower()))
        if has_pin and has_cues:
            detected_type = "branch"
        else:
            detected_type = "service_area"

    is_verified = detected_type in ("headquarters", "branch")

    return {
        "verified": is_verified,
        "location_type": detected_type,
        "evidence_excerpt": best_evidence[:250] or f"Located in {city}",
        "source_url": best_url or (crawled_pages[0]["url"] if crawled_pages else ""),
        "locality": matched_locality,
    }
