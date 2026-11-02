"""
Exports the Dakini AI SQLite Master Database (data/dakini_discovery.db) 
to native Microsoft Excel (.xlsx) and CSV files (.csv) with zero warnings.
"""

import csv
import os
import sqlite3
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dakini_discovery.db"


def col_to_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column letter (A, B, ..., Z, AA, AB, ...)."""
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def export_table_to_xlsx(
    conn: sqlite3.Connection,
    table_name: str,
    output_xlsx_path: Path,
    sheet_name: str = "Companies",
) -> int:
    """Export a SQLite table to a true, modern OpenXML spreadsheet (.xlsx) with no warnings."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    headers = [desc[0] for desc in cursor.description]

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

    safe_sheet = escape(sheet_name)[:31]
    wb = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    sheet_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '  <sheetData>',
    ]

    # Header row
    sheet_lines.append('    <row r="1">')
    for c_idx, h in enumerate(headers):
        ref = f"{col_to_letter(c_idx)}1"
        safe_val = escape(str(h) if h is not None else "")
        sheet_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
    sheet_lines.append('    </row>')

    # Data rows
    for r_idx, row in enumerate(rows, start=2):
        sheet_lines.append(f'    <row r="{r_idx}">')
        for c_idx, val in enumerate(row):
            ref = f"{col_to_letter(c_idx)}{r_idx}"
            safe_val = escape(str(val) if val is not None else "")
            sheet_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
        sheet_lines.append('    </row>')

    sheet_lines.append('  </sheetData>')
    sheet_lines.append('</worksheet>')
    sheet_content = "\n".join(sheet_lines)

    with zipfile.ZipFile(output_xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_content)

    return len(rows)


def export_table_to_csv(conn: sqlite3.Connection, table_name: str, output_csv_path: Path) -> int:
    """Export a SQLite table to a UTF-8 with BOM CSV file (natively opened by Excel)."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    headers = [desc[0] for desc in cursor.description]

    with open(output_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return len(rows)


def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    print("=" * 65)
    print(" Dakini AI - Master Database to Excel (.xlsx / .csv) Exporter")
    print("=" * 65)
    print(f"Source Database: {DB_PATH.resolve()}\n")

    # Clean up legacy .xls file if it exists to prevent extension warning
    legacy_xls = DATA_DIR / "companies_leads.xls"
    if legacy_xls.exists():
        try:
            legacy_xls.unlink()
        except Exception:
            pass

    # 1. Export Companies to genuine .xlsx and .csv
    comp_xlsx = DATA_DIR / "companies_leads.xlsx"
    comp_csv = DATA_DIR / "companies_leads.csv"
    c_count = export_table_to_xlsx(conn, "companies", comp_xlsx, sheet_name="Companies")
    export_table_to_csv(conn, "companies", comp_csv)
    print(f"[OK] Exported {c_count} companies to:")
    print(f"     - Excel (.xlsx): {comp_xlsx.resolve()}")
    print(f"     - Excel (.csv):  {comp_csv.resolve()}")

    # 2. Export Evidence
    ev_csv = DATA_DIR / "company_evidence.csv"
    ev_count = export_table_to_csv(conn, "company_evidence", ev_csv)
    print(f"\n[OK] Exported {ev_count} evidence records to:")
    print(f"     - CSV:   {ev_csv.resolve()}")

    # 3. Export Discovered URLs
    urls_csv = DATA_DIR / "discovered_urls.csv"
    urls_count = export_table_to_csv(conn, "discovered_urls", urls_csv)
    print(f"\n[OK] Exported {urls_count} discovered URLs to:")
    print(f"     - CSV:   {urls_csv.resolve()}")

    # 4. Export Runs
    runs_csv = DATA_DIR / "research_runs.csv"
    runs_count = export_table_to_csv(conn, "research_runs", runs_csv)
    print(f"\n[OK] Exported {runs_count} research run history records to:")
    print(f"     - CSV:   {runs_csv.resolve()}")

    conn.close()

    print("\n" + "=" * 65)
    print("All files are ready! You can open:")
    print(f"  • companies_leads.xlsx  (Opens natively in Excel without any warnings)")
    print(f"  • companies_leads.csv   (Universal CSV format)")
    print("=" * 65)


if __name__ == "__main__":
    main()
