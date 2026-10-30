from pathlib import Path
import csv
from typing import Iterable

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

FIELDS = [
    "company_name",
    "sector",
    "city",
    "state",
    "website",
    "phone",
    "email",
    "source",
    "contact_validation",
    "lead_quality_score",
    "score_reason",
]


def export_csv(leads: Iterable[dict], filename: str) -> str:
    path = OUTPUT_DIR / filename

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(leads)

    return str(path).replace("\\", "/")
