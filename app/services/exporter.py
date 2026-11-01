"""Structured export to CSV and Excel maintaining existing file naming and contracts."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from app.config import DATA_DIR

OUTPUT_DIR = DATA_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Preserved and extended export fields
FIELDS = [
    "company_name",
    "sector",
    "industry_subcategory",
    "country",
    "state",
    "city",
    "locality",
    "website",
    "phone",
    "email",
    "contact_person",
    "contact_role",
    "company_size",
    "company_age",
    "services",
    "location_type",
    "source",
    "contact_validation",
    "verification_status",
    "lead_quality_score",
    "score_reason",
]


def export_csv(leads: Iterable[dict[str, Any]], filename: str) -> str:
    """Export company records to CSV file using standard library csv."""
    path = OUTPUT_DIR / filename

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        for lead in leads:
            row = dict(lead)
            if isinstance(row.get("services"), list):
                row["services"] = "; ".join(row["services"])
            writer.writerow(row)

    return str(path).replace("\\", "/")


def export_excel(leads: Iterable[dict[str, Any]], filename: str) -> str:
    """Export company records to Excel (.xlsx) file with graceful CSV fallback."""
    xlsx_filename = filename if filename.endswith(".xlsx") else f"{filename.rsplit('.', 1)[0]}.xlsx"
    path = OUTPUT_DIR / xlsx_filename

    try:
        import pandas as pd
        df = pd.DataFrame(list(leads))
        # Ensure standard column order
        cols = [c for c in FIELDS if c in df.columns] + [c for c in df.columns if c not in FIELDS and not c.startswith("_")]
        df = df[cols]
        df.to_excel(path, index=False)
        return str(path).replace("\\", "/")
    except Exception:
        # Fallback to CSV if openpyxl/excel writer not available
        return export_csv(leads, filename)
