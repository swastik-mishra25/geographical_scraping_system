"""
Exports the Dakini AI SQLite Master Database (data/dakini_discovery.db)
to comprehensive Microsoft Excel (.xlsx) workbooks and CSV files (.csv)
containing BOTH All Discovery Data (candidate URLs, crawl status, queries)
AND Qualified Data (verified companies, evidence, policies, run histories).
Works with zero external dependencies (pure Python standard library).
"""

import csv
import os
import sqlite3
import zipfile
from pathlib import Path
from typing import Any
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


def export_multi_sheet_xlsx(
    sheets: list[tuple[str, list[str], list[list[Any]]]],
    output_xlsx_path: Path,
) -> int:
    """
    Export multiple sheets to a true, modern OpenXML spreadsheet (.xlsx)
    using only Python's standard library (zipfile + xml). Zero warnings in Excel.
    """
    content_types_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '  <Default Extension="xml" ContentType="application/xml"/>',
        '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    ]

    wb_rels_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]

    wb_sheets_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        '  <sheets>',
    ]

    sheet_xml_map: dict[str, str] = {}
    total_records = 0

    for idx, (title, headers, rows) in enumerate(sheets, start=1):
        total_records += len(rows)
        part_name = f"/xl/worksheets/sheet{idx}.xml"
        sheet_filename = f"xl/worksheets/sheet{idx}.xml"
        rel_id = f"rId{idx}"

        content_types_lines.append(
            f'  <Override PartName="{part_name}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        wb_rels_lines.append(
            f'  <Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        )
        safe_title = escape(str(title))[:31].replace(":", "_").replace("/", "_").replace("\\", "_")
        wb_sheets_lines.append(f'    <sheet name="{safe_title}" sheetId="{idx}" r:id="{rel_id}"/>')

        # Build sheetData
        s_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            '  <sheetData>',
            '    <row r="1">',
        ]
        for c_idx, h in enumerate(headers):
            ref = f"{col_to_letter(c_idx)}1"
            safe_val = escape(str(h) if h is not None else "")
            s_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
        s_lines.append('    </row>')

        for r_idx, row in enumerate(rows, start=2):
            s_lines.append(f'    <row r="{r_idx}">')
            for c_idx, val in enumerate(row):
                ref = f"{col_to_letter(c_idx)}{r_idx}"
                safe_val = escape(str(val) if val is not None else "")
                s_lines.append(f'      <c r="{ref}" t="inlineStr"><is><t>{safe_val}</t></is></c>')
            s_lines.append('    </row>')

        s_lines.append('  </sheetData>')
        s_lines.append('</worksheet>')
        sheet_xml_map[sheet_filename] = "\n".join(s_lines)

    content_types_lines.append('</Types>')
    wb_rels_lines.append('</Relationships>')
    wb_sheets_lines.append('  </sheets>')
    wb_sheets_lines.append('</workbook>')

    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "\n".join(content_types_lines))
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/_rels/workbook.xml.rels", "\n".join(wb_rels_lines))
        zf.writestr("xl/workbook.xml", "\n".join(wb_sheets_lines))
        for sheet_fname, sheet_content in sheet_xml_map.items():
            zf.writestr(sheet_fname, sheet_content)

    return total_records


def get_all_discovery_data(conn: sqlite3.Connection) -> tuple[list[str], list[list[Any]]]:
    """Retrieve full discovery pipeline data joining discovered_urls, crawl_frontier, domain_policy and companies."""
    cursor = conn.cursor()
    query = """
    SELECT 
        d.url_id,
        d.normalized_url,
        d.domain,
        d.discovery_query,
        d.discovery_method,
        d.discovered_at,
        d.relevance_status,
        COALESCE(f.status, d.crawl_status) AS crawl_status,
        f.priority,
        f.depth,
        f.retry_count,
        f.last_error,
        p.robots_status,
        p.crawl_permission_status,
        p.block_reason,
        c.company_name AS qualified_company_name,
        c.city AS verified_city,
        c.state AS verified_state,
        c.phone AS verified_phone,
        c.email AS verified_email,
        CASE 
            WHEN c.company_name IS NOT NULL THEN 'Qualified Lead'
            WHEN COALESCE(f.status, d.crawl_status) = 'failed' THEN 'Discovery (Crawl Failed)'
            WHEN COALESCE(f.status, d.crawl_status) = 'blocked' THEN 'Discovery (Crawl Blocked)'
            ELSE 'Discovery Candidate (Unqualified)'
        END AS pipeline_status
    FROM discovered_urls d
    LEFT JOIN crawl_frontier f ON d.url_id = f.url_id
    LEFT JOIN domain_policy p ON d.domain = p.domain
    LEFT JOIN companies c ON d.normalized_url = c.website OR (c.website != '' AND (instr(d.normalized_url, c.website) > 0 OR instr(c.website, d.domain) > 0))
    ORDER BY 
        CASE WHEN c.company_name IS NOT NULL THEN 0 ELSE 1 END,
        d.url_id
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    headers = [desc[0] for desc in cursor.description]
    return headers, [list(r) for r in rows]


def get_table_data(conn: sqlite3.Connection, table_name: str) -> tuple[list[str], list[list[Any]]]:
    """Fetch all rows and column headers from any SQLite table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    headers = [desc[0] for desc in cursor.description]
    return headers, [list(r) for r in rows]


def export_csv_file(headers: list[str], rows: list[list[Any]], output_path: Path) -> int:
    """Write data to a CSV with UTF-8 BOM encoding for direct Excel compatibility."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    print("=" * 70)
    print(" Dakini AI - Complete Discovery & Qualified Data Exporter")
    print("=" * 70)
    print(f"Source Database: {DB_PATH.resolve()}\n")

    # Clean up legacy .xls file if it exists to prevent extension warning
    legacy_xls = DATA_DIR / "companies_leads.xls"
    if legacy_xls.exists():
        try:
            legacy_xls.unlink()
        except Exception:
            pass

    # Gather data for all sheets
    disc_h, disc_r = get_all_discovery_data(conn)
    comp_h, comp_r = get_table_data(conn, "companies")
    ev_h, ev_r = get_table_data(conn, "company_evidence")
    pol_h, pol_r = get_table_data(conn, "domain_policy")
    runs_h, runs_r = get_table_data(conn, "research_runs")

    # Filter verified leads with phone numbers
    phone_col_idx = comp_h.index("phone") if "phone" in comp_h else -1
    phone_comp_rows = [r for r in comp_r if phone_col_idx >= 0 and r[phone_col_idx] and str(r[phone_col_idx]).strip()]

    delhi_rows: list[list[Any]] = []
    delhi_headers: list[str] = []
    delhi_csv = DATA_DIR / "delhi_digital_marketing_leads.csv"
    if delhi_csv.exists():
        try:
            with open(delhi_csv, encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.reader(f)
                d_all = list(reader)
                if d_all:
                    delhi_headers = d_all[0]
                    delhi_rows = d_all[1:]
        except Exception:
            pass

    # Assemble sheets: All Discovery Data first, then Qualified Companies, Leads with Phone, etc.
    sheets_data = [
        ("All Discovery Data", disc_h, disc_r),
        ("Qualified Companies", comp_h, comp_r),
        ("Leads With Available Phone", comp_h, phone_comp_rows),
    ]
    if delhi_rows:
        sheets_data.append(("Delhi Regional Leads", delhi_headers, delhi_rows))
    sheets_data.extend([
        ("Company Evidence", ev_h, ev_r),
        ("Domain Policies", pol_h, pol_r),
        ("Research Runs", runs_h, runs_r),
    ])

    # 1. Master Multi-sheet Excel (companies_leads.xlsx & all_discovery_data.xlsx)
    master_xlsx = DATA_DIR / "companies_leads.xlsx"
    discovery_xlsx = DATA_DIR / "all_discovery_data.xlsx"

    export_multi_sheet_xlsx(sheets_data, master_xlsx)
    export_multi_sheet_xlsx(sheets_data, discovery_xlsx)
    print(f"[OK] Master Multi-Sheet Excel Workbooks Generated (Zero Dependencies):")
    print(f"     - {master_xlsx.resolve()}")
    print(f"     - {discovery_xlsx.resolve()}")
    print(f"       Includes 6 sheets: All Discovery Data ({len(disc_r)}), Qualified Companies ({len(comp_r)}), Delhi Leads ({len(delhi_rows)}), Evidence ({len(ev_r)}), Policies ({len(pol_r)}), Runs ({len(runs_r)})\n")

    # 2. Export All Discovery Data CSV
    disc_csv = DATA_DIR / "all_discovery_data.csv"
    export_csv_file(disc_h, disc_r, disc_csv)
    print(f"[OK] Exported {len(disc_r)} All Discovery Data records to:")
    print(f"     - CSV: {disc_csv.resolve()}")

    # 3. Export individual tables to CSV
    comp_csv = DATA_DIR / "companies_leads.csv"
    export_csv_file(comp_h, comp_r, comp_csv)
    print(f"[OK] Exported {len(comp_r)} Qualified Companies to: {comp_csv.resolve()}")

    phone_csv = DATA_DIR / "companies_with_phone.csv"
    export_csv_file(comp_h, phone_comp_rows, phone_csv)
    print(f"[OK] Exported {len(phone_comp_rows)} Verified Phone Leads to: {phone_csv.resolve()}")

    urls_h, urls_r = get_table_data(conn, "discovered_urls")
    urls_csv = DATA_DIR / "discovered_urls.csv"
    export_csv_file(urls_h, urls_r, urls_csv)
    print(f"[OK] Exported {len(urls_r)} Discovered URLs to: {urls_csv.resolve()}")

    ev_csv = DATA_DIR / "company_evidence.csv"
    export_csv_file(ev_h, ev_r, ev_csv)
    print(f"[OK] Exported {len(ev_r)} Evidence records to: {ev_csv.resolve()}")

    pol_csv = DATA_DIR / "domain_policies.csv"
    export_csv_file(pol_h, pol_r, pol_csv)
    print(f"[OK] Exported {len(pol_r)} Domain Policy records to: {pol_csv.resolve()}")

    runs_csv = DATA_DIR / "research_runs.csv"
    export_csv_file(runs_h, runs_r, runs_csv)
    print(f"[OK] Exported {len(runs_r)} Research Runs to: {runs_csv.resolve()}")

    conn.close()
    print("\n" + "=" * 70)
    print("All Discovery & Qualified Data files are ready!")
    print("=" * 70)


if __name__ == "__main__":
    main()
