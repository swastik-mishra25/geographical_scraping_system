from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    country: str = "India"
    state: str = ""
    city: str
    category: str = "Digital Marketing"
    limit: int = Field(default=25, ge=1)
    phone_required: bool = False


class Lead(BaseModel):
    company_name: str
    sector: str = "Digital Marketing"
    city: str = ""
    state: str = ""
    website: str = ""
    phone: str = ""
    has_phone: bool = False
    phone_type: str = "none"
    email: str = ""
    source: str = "OpenStreetMap"
    contact_validation: str = ""
    lead_quality_score: int = Field(default=0, ge=0, le=100)
    score_reason: str = ""
    evidence: List[str] = []


class ScrapeResponse(BaseModel):
    requested_city: str
    requested_category: str
    discovered: int
    qualified: int
    leads_with_phone: int = 0
    phone_required: bool = False
    leads: List[Lead]
    discovery_data: List[Dict[str, Any]] = []
    csv_file: str
    phone_leads_csv_file: str = ""
    discovery_csv_file: str = ""
    master_excel_file: str = ""
