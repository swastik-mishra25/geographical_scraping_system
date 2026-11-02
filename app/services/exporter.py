"""Structured export to CSV and native Excel (.xlsx) maintaining existing file naming and contracts."""
from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

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


def _col_to_letter(col_idx: int) -> str:
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


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
    """Export company records to native Microsoft Excel (.xlsx) file without external dependencies."""
    xlsx_filename = filename if filename.endswith(".xlsx") else f"{filename.rsplit('.', 1)[0]}.xlsx"
    path = OUTPUT_DIR / xlsx_filename

    lead_list = list(leads)
    headers = [f for f in FIELDS]

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    wb_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

    wb = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Leads" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    sheet_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '  <sheetData>',
        '    <row r="1">',
    ]
    for c_idx, h in enumerate(headers):
        ref = f"{_col_to_letter(c_idx)}1"
        safe_val = escape(str(h))
        sheet_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
    sheet_lines.append('    </row>')

    for r_idx, lead in enumerate(lead_list, start=2):
        sheet_lines.append(f'    <row r="{r_idx}">')
        for c_idx, h in enumerate(headers):
            ref = f"{_col_to_letter(c_idx)}{r_idx}"
            val = lead.get(h, "")
            if isinstance(val, list):
                val = "; ".join(str(item) for item in val)
            safe_val = escape(str(val) if val is not None else "")
            sheet_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
        sheet_lines.append('    </row>')

    sheet_lines.append('  </sheetData>')
    sheet_lines.append('</worksheet>')
    sheet_content = "\n".join(sheet_lines)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_content)

    return str(path).replace("\\", "/")
