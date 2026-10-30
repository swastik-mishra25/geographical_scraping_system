from typing import List
from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    country: str = "India"
    state: str = ""
    city: str
    category: str = "Digital Marketing"
    limit: int = Field(default=25, ge=1)


class Lead(BaseModel):
    company_name: str
    sector: str = "Digital Marketing"
    city: str = ""
    state: str = ""
    website: str = ""
    phone: str = ""
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
    leads: List[Lead]
    csv_file: str
