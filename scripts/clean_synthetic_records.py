"""Migration script to purge synthetic catalog fallback records from dakini_discovery.db."""
import sqlite3

def clean_database(db_path: str = "data/dakini_discovery.db"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Find IDs of synthetic companies
    c.execute("""
        SELECT company_id 
        FROM companies 
        WHERE website LIKE '%-delhi.in%' 
           OR website LIKE '%-mumbai.in%' 
           OR website LIKE '%-bhubaneswar.in%'
           OR website LIKE '%-chennai.in%'
           OR website LIKE '%-kolkata.in%'
           OR website LIKE '%-pune.in%'
           OR website LIKE '%-bengaluru.in%'
           OR website LIKE '%horizonsolutions.in%'
           OR website LIKE '%blazesolutions.in%'
           OR website LIKE '%digitalwavesolutions.in%'
           OR website LIKE '%truenorthsolutions.in%'
           OR website LIKE '%kineticsolutions.in%'
           OR website LIKE '%fluxsolutions.in%'
           OR website LIKE '%atlassolutions.in%'
           OR website LIKE '%zenithtechnologies.in%'
           OR website LIKE '%pinnacletechnologies.in%'
           OR website LIKE '%vanguardtechnologies.in%'
           OR website LIKE '%smart%appsbhubaneswar%'
           OR website LIKE '%crown%digitalsolutions%'
    """)
    synthetic_ids = [row[0] for row in c.fetchall()]
    print(f"[migration] Identified {len(synthetic_ids)} synthetic records to purge.")

    if synthetic_ids:
        placeholders = ",".join("?" for _ in synthetic_ids)
        # Delete from company_evidence
        c.execute(f"DELETE FROM company_evidence WHERE company_id IN ({placeholders})", synthetic_ids)
        # Delete from companies
        c.execute(f"DELETE FROM companies WHERE company_id IN ({placeholders})", synthetic_ids)
        conn.commit()
        print(f"[migration] Successfully purged {len(synthetic_ids)} synthetic companies and evidence.")

    remaining = c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    remaining_phones = c.execute("SELECT COUNT(*) FROM companies WHERE phone != '' AND phone IS NOT NULL").fetchone()[0]
    print(f"[migration] Clean Database Status: {remaining} genuine qualified companies ({remaining_phones} with phone).")

    conn.close()

if __name__ == "__main__":
    clean_database()
