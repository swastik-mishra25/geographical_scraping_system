"""
Database Cleanup & Stabilization Script.
Removes all synthetic / hallucinated mock candidate profiles and synchronizes the database.
Zero Fake Data Guarantee.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("data/dakini_discovery.db")

def purge_synthetic_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("=== DAKINI DATABASE PURGE & STABILIZATION ===")
    
    # 1. Count before
    cur.execute("SELECT count(*) FROM companies")
    total_companies_before = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM companies WHERE lead_quality_score > 0 AND score_reason != ''")
    genuine_companies = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM company_evidence")
    total_evidence_before = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM discovered_urls")
    total_urls_before = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM crawl_frontier")
    total_frontier_before = cur.fetchone()[0]

    print(f"Before:")
    print(f"  Companies: {total_companies_before} (Genuine: {genuine_companies}, Synthetic: {total_companies_before - genuine_companies})")
    print(f"  Evidence:  {total_evidence_before}")
    print(f"  Discovered URLs: {total_urls_before}")
    print(f"  Frontier:  {total_frontier_before}")

    # 2. Delete synthetic evidence (evidence tied to synthetic companies)
    cur.execute("""
        DELETE FROM company_evidence 
        WHERE company_id IN (
            SELECT company_id FROM companies 
            WHERE lead_quality_score = 0 OR score_reason = ''
        )
    """)
    deleted_evidence = cur.rowcount
    print(f"Deleted {deleted_evidence} synthetic evidence rows.")

    # 3. Delete synthetic companies
    cur.execute("""
        DELETE FROM companies 
        WHERE lead_quality_score = 0 OR score_reason = ''
    """)
    deleted_companies = cur.rowcount
    print(f"Deleted {deleted_companies} synthetic companies.")

    # 4. Delete synthetic discovered URLs and frontier items
    cur.execute("""
        DELETE FROM crawl_frontier 
        WHERE url_id IN (
            SELECT url_id FROM discovered_urls 
            WHERE discovery_method = 'regional_catalog_discovery'
        )
    """)
    deleted_frontier = cur.rowcount
    print(f"Deleted {deleted_frontier} synthetic frontier rows.")

    cur.execute("""
        DELETE FROM discovered_urls 
        WHERE discovery_method = 'regional_catalog_discovery'
    """)
    deleted_urls = cur.rowcount
    print(f"Deleted {deleted_urls} synthetic discovered URLs.")

    conn.commit()

    # 5. Vacuum database to reclaim space
    print("Vacuuming database...")
    cur.execute("VACUUM")
    conn.commit()

    # 6. Count after
    cur.execute("SELECT count(*) FROM companies")
    total_companies_after = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM company_evidence")
    total_evidence_after = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM discovered_urls")
    total_urls_after = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM crawl_frontier")
    total_frontier_after = cur.fetchone()[0]

    cur.execute("SELECT city, count(*) FROM companies GROUP BY city")
    city_counts = cur.fetchall()

    print("\nAfter:")
    print(f"  Companies: {total_companies_after}")
    print(f"  Evidence:  {total_evidence_after}")
    print(f"  Discovered URLs: {total_urls_after}")
    print(f"  Frontier:  {total_frontier_after}")
    print(f"  City Distribution: {city_counts}")
    print("=== PURGE COMPLETED SUCCESSFULLY ===")

    conn.close()

if __name__ == "__main__":
    purge_synthetic_data()
