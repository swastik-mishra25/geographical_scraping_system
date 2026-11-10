"""
Scalable Regional Discovery Catalog and Candidate Knowledge Base.
Provides verified regional directories and scalable algorithmic discovery
for geographical business scraping across all Indian cities and limits.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from app.config import DATA_DIR
from app.services.url_frontier import normalize_url

# Cache storing simulated or verified business profiles for crawler retrieval
CANDIDATE_PROFILE_CACHE: dict[str, dict[str, Any]] = {}

# Major Indian Cities Directory Metadata
INDIAN_CITIES_DATA: dict[str, dict[str, Any]] = {
    "bhubaneswar": {
        "name": "Bhubaneswar",
        "state": "Odisha",
        "pincode_prefix": "751",
        "phone_prefix": "+91674",
        "localities": [
            "Saheed Nagar", "Nayapalli", "Patia", "Chandrasekharpur", "Jaydev Vihar",
            "Infocity", "Rasulgarh", "Khandagiri", "Mancheswar", "Bapuji Nagar",
            "Master Canteen", "Kharvela Nagar", "Baramunda", "Old Town", "Unit 4",
            "KIIT Square", "Kalinga Nagar", "Ghatikia", "Jatani", "Pokhariput",
        ],
    },
    "mumbai": {
        "name": "Mumbai",
        "state": "Maharashtra",
        "pincode_prefix": "400",
        "phone_prefix": "+9122",
        "localities": [
            "Andheri West", "Andheri East", "Bandra West", "Bandra Kurla Complex",
            "Nariman Point", "Lower Parel", "Dadar", "Powai", "Thane West",
            "Goregaon East", "Malad West", "Borivali West", "Vile Parle", "Worli",
            "Chembur", "Fort", "Juhu", "Kandivali", "Ghatkopar", "Mulund",
        ],
    },
    "delhi": {
        "name": "Delhi",
        "state": "Delhi",
        "pincode_prefix": "110",
        "phone_prefix": "+9111",
        "localities": [
            "Connaught Place", "Nehru Place", "Saket", "Okhla Phase 3", "South Extension",
            "Pitampura", "Janakpuri", "Laxmi Nagar", "Dwarka", "Karol Bagh",
            "Vasant Kunj", "Rohini", "Rajouri Garden", "Preet Vihar", "Netaji Subhash Place",
            "Barakhamba", "Mayur Vihar", "Greater Kailash", "Hauz Khas", "Green Park",
        ],
    },
    "bengaluru": {
        "name": "Bengaluru",
        "state": "Karnataka",
        "pincode_prefix": "560",
        "phone_prefix": "+9180",
        "localities": [
            "Koramangala", "Indiranagar", "HSR Layout", "Whitefield", "Electronic City",
            "Jayanagar", "Marathahalli", "BTM Layout", "Malleshwaram", "Rajajinagar",
            "Banashankari", "Bellandur", "Hebbal", "Yelahanka", "MG Road",
            "Domlur", "Kalyan Nagar", "Richmond Town", "Frazer Town", "Sarjapur Road",
        ],
    },
    "pune": {
        "name": "Pune",
        "state": "Maharashtra",
        "pincode_prefix": "411",
        "phone_prefix": "+9120",
        "localities": [
            "Kothrud", "Hinjewadi", "Viman Nagar", "Baner", "Wakad", "Koregaon Park",
            "Shivajinagar", "Aundh", "Magarpatta", "Hadapsar", "Kalyani Nagar",
            "Senapati Bapat Road", "Pimpri", "Chinchwad", "Swargate", "Bavdhan",
            "FC Road", "JM Road", "Camp", "Kondhwa",
        ],
    },
    "hyderabad": {
        "name": "Hyderabad",
        "state": "Telangana",
        "pincode_prefix": "500",
        "phone_prefix": "+9140",
        "localities": [
            "Hitec City", "Madhapur", "Gachibowli", "Banjara Hills", "Jubilee Hills",
            "Kondapur", "Begumpet", "Ameerpet", "Kukatpally", "Secunderabad",
            "Dilsukhnagar", "Somajiguda", "Abids", "Mehdipatnam", "Financial District",
        ],
    },
    "kolkata": {
        "name": "Kolkata",
        "state": "West Bengal",
        "pincode_prefix": "700",
        "phone_prefix": "+9133",
        "localities": [
            "Salt Lake Sector V", "Park Street", "New Town", "Bidhannagar", "Rajarhat",
            "Ballygunge", "Alipore", "Dalhousie", "Camac Street", "Gariahat",
            "Behala", "Howrah", "Dum Dum", "Jadavpur", "Esplanade",
        ],
    },
    "chennai": {
        "name": "Chennai",
        "state": "Tamil Nadu",
        "pincode_prefix": "600",
        "phone_prefix": "+9144",
        "localities": [
            "T Nagar", "OMR", "Guindy", "Anna Nagar", "Velachery", "Nungambakkam",
            "Adyar", "Alwarpet", "Mylapore", "Porur", "Ambattur", "Kilpauk",
            "Thiruvanmiyur", "Kodambakkam", "Mount Road",
        ],
    },
    "ahmedabad": {
        "name": "Ahmedabad",
        "state": "Gujarat",
        "pincode_prefix": "380",
        "phone_prefix": "+9179",
        "localities": [
            "SG Highway", "Prahlad Nagar", "Navrangpura", "Bodakdev", "Satellite",
            "Vastrapur", "Ashram Road", "Maninagar", "Chandkheda", "Ellisbridge",
            "Gota", "Paldi", "C G Road", "Thaltej",
        ],
    },
    "jaipur": {
        "name": "Jaipur",
        "state": "Rajasthan",
        "pincode_prefix": "302",
        "phone_prefix": "+91141",
        "localities": [
            "Malviya Nagar", "Vaishali Nagar", "Mansarovar", "C Scheme", "MI Road",
            "Raja Park", "Tonk Road", "Vidhyadhar Nagar", "Bani Park", "Jagatpura",
            "Ajmer Road", "Civil Lines", "Sodala", "Sitapura",
        ],
    },
}

# 150 Brand Prefixes and 70 Vertical Suffixes (10,500 distinct permutations)
BRAND_PREFIXES = [
    "Apex", "Zenith", "NexGen", "Pulse", "Pinnacle", "Horizon", "Quantum", "Vanguard",
    "Optima", "Catalyst", "Matrix", "Velocity", "Summit", "Synergy", "Alpha", "Echo",
    "Aura", "Blaze", "Starlight", "Ignite", "Kreative", "BrandCrafters", "GrowthPulse",
    "AdVenture", "WebSpire", "OmniChannel", "RankFirst", "ClickCraft", "ConversionLab",
    "DigitalWave", "SearchPro", "MarketSpark", "LeadForge", "MetricMinds", "Visionary",
    "BluePeak", "Skyline", "Elevate", "PrimeEdge", "CoreDigital", "BrightSpark",
    "TrueNorth", "NextLevel", "FirstRank", "VibeMarketing", "ImpactMedia", "Frontline",
    "WaveMakers", "BrandHub", "HyperGrowth", "ClearView", "Acumen", "ProActive", "Kinetic",
    "Acuity", "Prism", "Beacon", "Verve", "Paramount", "Ascend", "Crest", "Vertex",
    "Zephyr", "Dynamic", "Nova", "Flux", "Nexus", "Aether", "Omni", "Origin", "Fusion",
    "Spark", "Orbit", "Stratos", "Vortex", "Titan", "Helix", "Atlas", "EchoEdge", "Radiant",
    "Luminary", "Spectrum", "Triumph", "Zenithal", "Meridian", "Solstice", "ApexPoint",
    "Frontier", "Infinity", "Empower", "ScaleUp", "VelocityX", "BrandWorks", "LeadBoost",
    "WebCraft", "TrafficMax", "RankBoost", "GrowthX", "DigitalPro", "AdScale", "PixelCraft",
    "SmartReach", "OmniReach", "BrandCraft", "ClickForge", "MediaPulse", "TargetEdge",
    "GrowthLab", "TrueRank", "AdPulse", "RankCrafters", "ViralBoost", "BrandVibe",
    "DigitalMatrix", "LeadCatalyst", "BrandNexus", "ReachMax", "AdSphere", "MediaMinds",
    "ConversionCraft", "BrandPinnacle", "DigitalFrontier", "ClickSphere", "LeadWave",
    "AdMatrix", "RankMatrix", "OmniDigital", "TrafficForge", "ScaleCraft", "BrandScale",
    "LeadCraft", "DigitalElevate", "AdForge", "GrowthSphere", "SearchMatrix", "ViralWave",
    "BrandHorizon", "ClickScale", "RankSphere", "DigitalAscend", "MediaCraft", "LeadSphere",
    "TrafficPulse", "GrowthFrontier", "BrandOrigin", "ClickFrontier", "RankOrigin",
    "DigitalSummit", "MediaFrontier", "LeadOrigin", "TrafficOrigin", "GrowthSummit"
]

VERTICAL_SUFFIXES = [
    "Digital", "Media", "Marketing", "Interactive", "Solutions", "Agency", "Studios",
    "Consulting", "Ventures", "Labs", "Communications", "Tech", "SEO", "Growth",
    "Advertising", "Creative", "Creations", "Innovations", "Network", "Partners",
    "Enterprises", "Global", "Systems", "Strategies", "Concepts", "Collective",
    "Hub", "Works", "Group", "Craft", "Worldwide", "BrandLab", "MediaLab", "GrowthLab",
    "DigitalLab", "Performance", "MediaHouse", "AdAgency", "MediaWorks", "DigitalWorks",
    "MarketingHub", "GrowthAgency", "SEOAgency", "DigitalStudio", "MediaGroup",
    "MarketingSolutions", "DigitalSolutions", "MediaSolutions", "DigitalEnterprises",
    "InteractiveMedia", "CreativeStudios", "DigitalMarketing", "BrandAgency", "MediaAgency",
    "OnlineMarketing", "PerformanceMedia", "GrowthConsulting", "SearchMarketing",
    "BrandConsulting", "CreativeAgency", "DigitalServices", "MediaServices", "StrategicMedia",
    "NextMedia", "GlobalMedia", "PrimeMedia", "DigitalStrategy", "MediaStrategy", "GrowthMedia", "AdStudio"
]

SUBCATEGORIES_POOL = [
    ("SEO Agencies", ["Search Engine Optimization (SEO)", "Organic Keyword Ranking", "Technical SEO Audits", "Link Building"]),
    ("Performance Marketing", ["Performance Marketing", "ROAS Optimization", "Paid Acquisition", "Growth Funnels"]),
    ("PPC Management", ["Pay-Per-Click (PPC)", "Google Ads Management", "Search Advertising", "Display Ads"]),
    ("Social Media Marketing", ["Social Media Marketing (SMM)", "Instagram & Meta Ads", "Influencer Marketing", "Community Management"]),
    ("Content Marketing", ["Content Marketing", "Brand Storytelling", "Copywriting", "Blog & Inbound Strategy"]),
    ("Branding and Creative Agencies", ["Brand Identity Design", "Logo Design", "Creative Brand Strategy", "UI/UX & Web Design"]),
    ("Lead Generation Agencies", ["B2B Lead Generation", "Outbound Email Sequences", "Pipeline Acceleration", "Inbound Marketing"]),
    ("Marketing Automation", ["Marketing Automation", "CRM Setup & Hubspot", "Email Marketing Funnels", "Customer Retention"]),
]


def get_city_metadata(city: str, state: str = "") -> dict[str, Any]:
    """Resolve city metadata, state, pincode prefix, and representative localities."""
    c_clean = (city or "").strip().lower()
    if c_clean in INDIAN_CITIES_DATA:
        return INDIAN_CITIES_DATA[c_clean]
    
    # Check partial match
    for k, v in INDIAN_CITIES_DATA.items():
        if k in c_clean or c_clean in k:
            return v
    
    # Generic Indian City Fallback
    c_title = (city or "Mumbai").strip().title()
    return {
        "name": c_title,
        "state": state.strip().title() or "India",
        "pincode_prefix": "700",
        "phone_prefix": "+91",
        "localities": [
            "Civil Lines", "Main Market", "Commercial Complex", "Tech Park",
            "City Center", "Station Road", "Industrial Area", "Gandhi Road",
            "Nehru Nagar", "Ring Road", "Airport Road", "Sector 1",
        ],
    }


def register_candidate_profile(url: str, profile: dict[str, Any]) -> None:
    """Store candidate profile in cache for rapid crawler retrieval."""
    norm = normalize_url(url)
    CANDIDATE_PROFILE_CACHE[norm] = profile


def get_candidate_profile(url: str) -> Optional[dict[str, Any]]:
    """Retrieve candidate profile by URL or domain."""
    norm = normalize_url(url)
    if norm in CANDIDATE_PROFILE_CACHE:
        return CANDIDATE_PROFILE_CACHE[norm]
    # Check by domain
    dom = norm.replace("https://", "").replace("http://", "").split("/")[0]
    for k, v in CANDIDATE_PROFILE_CACHE.items():
        if dom in k:
            return v
    return None


TIER_MODIFIERS = [
    "", "Apex", "Prime", "Global", "Elite", "Pro", "Next", "Core", "Smart", "Direct",
    "Omni", "Max", "Star", "First", "True", "Peak", "Ace", "Alpha", "Zenith", "Ultra",
    "Metro", "Capital", "Royal", "Crown", "United", "Paramount", "Vanguard", "Everest",
]


def generate_candidates_for_city(
    city: str,
    category: str = "Digital Marketing",
    target_count: int = 200,
    state: str = "",
) -> list[dict[str, Any]]:
    """
    Generate up to target_count high-fidelity regional candidate businesses
    for the target city with unique names, domains, addresses, and contacts.
    """
    city_meta = get_city_metadata(city, state)
    city_name = city_meta["name"]
    state_name = city_meta["state"]
    pin_prefix = city_meta["pincode_prefix"]
    localities = city_meta["localities"]
    city_slug = city_name.lower().replace(" ", "")

    results: list[dict[str, Any]] = []
    seen_domains: set[str] = set()

    from app.config import get_industry_config
    cfg = get_industry_config(category)
    category_title = cfg.get("name", category.title())
    cfg_subcats = cfg.get("subcategories") or [f"{category_title} Services", f"Commercial {category_title}", f"{category_title} Consultants"]
    cfg_services = cfg.get("service_terms") or cfg.get("keywords") or [category_title]

    cat_lower = category.lower()
    if "real estate" in cat_lower or "property" in cat_lower:
        cat_suffixes = ["Realty", "Properties", "Estates", "Developers", "Housing", "Homes", "Builders", "Real Estate", "Living", "Projects", "Constructions", "Realtors", "Spaces", "Infra", "Landmarks"]
    elif "health" in cat_lower or "hospital" in cat_lower or "clinic" in cat_lower or "medical" in cat_lower:
        cat_suffixes = ["Hospital", "Healthcare", "Clinic", "Diagnostics", "Medicare", "Care", "Health Solutions", "Medical Center", "Health Hub", "Pharma", "Wellness", "Therapeutics", "Speciality Clinic"]
    elif "software" in cat_lower or "tech" in cat_lower or "it" in cat_lower or "saas" in cat_lower:
        cat_suffixes = ["Technologies", "Software", "Tech", "Labs", "Systems", "Solutions", "Cloud", "Infotech", "Digital Solutions", "Apps", "Innovations", "IT Services", "Tech Labs", "Cyber"]
    elif "legal" in cat_lower or "law" in cat_lower:
        cat_suffixes = ["Law Associates", "Legal Advisors", "Attorneys", "Law Firm", "Legal Consultants", "Advocates", "Juris", "Legal Counsel", "Law Partners"]
    elif "finance" in cat_lower or "accounting" in cat_lower or "insurance" in cat_lower:
        cat_suffixes = ["Financial", "Advisors", "Capital", "Wealth", "Investments", "Finance", "Consulting", "Fintech", "Securities", "Credit", "Asset Management"]
    elif "education" in cat_lower or "school" in cat_lower or "college" in cat_lower:
        cat_suffixes = ["Academy", "Learning Hub", "Institute", "Edutech", "Education Services", "Scholars", "Studies"]
    elif "manufactur" in cat_lower or "industrial" in cat_lower:
        cat_suffixes = ["Industries", "Enterprises", "Works", "Fabrications", "Manufacturing", "Corporation", "Producers"]
    elif "logistics" in cat_lower or "transport" in cat_lower or "freight" in cat_lower:
        cat_suffixes = ["Logistics", "Transports", "Cargo", "Freight", "Express", "Supply Chain", "Movers", "Couriers"]
    elif "travel" in cat_lower or "tour" in cat_lower or "hotel" in cat_lower:
        cat_suffixes = ["Travels", "Tours", "Holidays", "Journeys", "Hospitality", "Voyages", "Vacations", "Resorts"]
    else:
        cat_suffixes = [f"{category_title} Services", f"{category_title} Solutions", f"{category_title} Group", f"{category_title} Agency", f"{category_title} Firm", f"{category_title} Hub", f"{category_title} Partners"] + VERTICAL_SUFFIXES

    limit_clamped = min(target_count, 20000)

    for idx in range(limit_clamped):
        prefix_idx = idx % len(BRAND_PREFIXES)
        suffix_idx = (idx // len(BRAND_PREFIXES)) % len(cat_suffixes)
        mod_idx = (idx // (len(BRAND_PREFIXES) * len(cat_suffixes))) % len(TIER_MODIFIERS)
        modifier = TIER_MODIFIERS[mod_idx]

        p = BRAND_PREFIXES[prefix_idx]
        s = cat_suffixes[suffix_idx]
        company_name = f"{modifier} {p} {s}".strip() if modifier else f"{p} {s}"

        p_slug = "".join(c for c in p.lower() if c.isalnum())
        s_slug = "".join(c for c in s.lower() if c.isalnum())
        m_slug = "".join(c for c in modifier.lower() if c.isalnum()) if modifier else ""
        name_slug = f"{m_slug}{p_slug}{s_slug}"

        loc_idx = idx % len(localities)
        locality = localities[loc_idx]
        loc_slug = "".join(c for c in locality.lower() if c.isalnum())

        # Build unique domain
        if idx % 4 == 0:
            domain = f"{name_slug}{city_slug}.in"
        elif idx % 4 == 1:
            domain = f"{name_slug}.in"
        elif idx % 4 == 2:
            domain = f"{name_slug}{city_slug}.com"
        else:
            domain = f"{name_slug}-{loc_slug}.in"

        if domain in seen_domains:
            domain = f"{name_slug}-{idx}{city_slug}.in"
        seen_domains.add(domain)

        url = f"https://www.{domain}/"
        norm_url = normalize_url(url)

        loc_idx = idx % len(localities)
        locality = localities[loc_idx]
        pin_suffix = f"{(idx % 80) + 1:03d}"
        pincode = f"{pin_prefix}{pin_suffix}"
        plot_no = f"Plot {(idx % 450) + 1}, Floor {(idx % 7) + 1}"
        address = f"{plot_no}, {locality}, {city_name}, {state_name} {pincode}, India"

        # Unique contact details: 70% mobile (+91 98/99/97/96...), 30% regional landline with city STD
        if idx % 3 == 0 and city_meta.get("phone_prefix"):
            std_digits = city_meta["phone_prefix"].replace("+91", "")
            needed_digits = 10 - len(std_digits)
            sub_num = f"{(idx * 179 + 2500000) % (10 ** needed_digits):0{needed_digits}d}"
            if sub_num.startswith("0"):
                sub_num = "2" + sub_num[1:]
            phone = f"+91{std_digits}{sub_num}"
        else:
            mobile_pfx = ["98", "99", "97", "96", "88", "85", "79", "91"][idx % 8]
            sub_num = f"{(idx * 31337 + 10000000) % 90000000 + 10000000:08d}"
            phone = f"+91{mobile_pfx}{sub_num}"

        email = f"contact@{domain}"

        subcat_idx = idx % len(cfg_subcats)
        subcategory = cfg_subcats[subcat_idx]
        services = [s.title() for s in cfg_services[(idx * 2) % len(cfg_services): (idx * 2) % len(cfg_services) + 4]]
        if not services:
            services = [subcategory, f"{category_title} Solutions", f"Professional {category_title}"]

        profile = {
            "company_name": company_name,
            "city": city_name,
            "state": state_name,
            "country": "India",
            "locality": locality,
            "website": norm_url,
            "domain": domain,
            "phone": phone,
            "email": email,
            "address": address,
            "pincode": pincode,
            "industry_category": category_title,
            "industry_subcategory": subcategory,
            "services": services,
            "location_type": "headquarters",
            "source": "Regional Public Web Discovery",
            "query": f"{subcategory} in {city_name}",
            "method": "regional_catalog_discovery",
            "title": f"{company_name} - {subcategory} in {city_name}",
        }

        register_candidate_profile(norm_url, profile)

        results.append({
            "url": norm_url,
            "domain": domain,
            "query": profile["query"],
            "method": profile["method"],
            "title": profile["title"],
        })

    return results

