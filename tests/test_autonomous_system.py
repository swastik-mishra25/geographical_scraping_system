"""Comprehensive test suite for the Dakini Autonomous Public-Web Business Discovery System.
Covers all 15 Phase E acceptance test scenarios.
"""
import os
import unittest
import warnings
from unittest.mock import MagicMock, patch

warnings.filterwarnings("ignore", category=UserWarning, module=r"fastapi(\._compat\.v1)?")

from app.config import get_industry_config
from app.services.crawl_policy import (
    check_crawl_permission,
    detect_anti_bot_or_auth,
    is_safe_public_url,
)
from app.services.dedupe import IndexedDeduplicator
from app.services.extraction import extract_business_data, normalize_indian_phone
from app.services.industry_classifier import classify_industry
from app.services.location_verifier import verify_location
from app.services.orchestrator import execute_autonomous_run
from app.services.persistence import (
    create_research_run,
    get_latest_checkpoint,
    init_db,
    save_checkpoint,
    save_company,
    update_research_run,
)
from app.services.query_generator import generate_discovery_queries
from app.services.validation import validate_lead


class TestAutonomousSystemSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db = "data/test_autonomous.db"
        init_db(cls.test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db):
            try:
                os.remove(cls.test_db)
            except Exception:
                pass

    # 1. Digital marketing + Mumbai
    def test_01_digital_marketing_mumbai_queries(self):
        queries = generate_discovery_queries("Digital Marketing", city="Mumbai", state="Maharashtra")
        self.assertGreaterEqual(len(queries), 3)
        q_texts = [q["query"].lower() for q in queries]
        self.assertTrue(any("mumbai" in q for q in q_texts))
        self.assertTrue(any("seo" in q or "digital marketing" in q for q in q_texts))

    # 2. Digital marketing + Bhubaneswar
    def test_02_digital_marketing_bhubaneswar_queries(self):
        queries = generate_discovery_queries("Digital Marketing", city="Bhubaneswar", state="Odisha")
        self.assertGreaterEqual(len(queries), 3)
        q_texts = [q["query"].lower() for q in queries]
        self.assertTrue(any("bhubaneswar" in q for q in q_texts))
        self.assertTrue(any("agency" in q or "company" in q for q in q_texts))

    # 3. A company with a verified headquarters address
    def test_03_verified_headquarters_address(self):
        crawled_pages = [
            {
                "url": "https://apexdigital.in/contact",
                "page_type": "contact",
                "text": "Headquarters & Corporate Office: 501 Lotus Grandeur, Veera Desai Road, Andheri West, Mumbai 400053, Maharashtra.",
            }
        ]
        res = verify_location("Mumbai", "Maharashtra", "India", "Andheri", crawled_pages)
        self.assertTrue(res["verified"])
        self.assertEqual(res["location_type"], "headquarters")
        self.assertIn("Mumbai 400053", res["evidence_excerpt"])

    # 4. A company with a branch in the target city
    def test_04_verified_branch_office(self):
        crawled_pages = [
            {
                "url": "https://globalmarketing.com/locations",
                "page_type": "contact",
                "text": "Our Branch Office: Infocity Square, Patia, Bhubaneswar, Odisha 751024. Ph: +919876543210",
            }
        ]
        res = verify_location("Bhubaneswar", "Odisha", "India", "Patia", crawled_pages)
        self.assertTrue(res["verified"])
        self.assertEqual(res["location_type"], "branch")
        self.assertIn("Bhubaneswar", res["evidence_excerpt"])

    # 5. A company that only mentions the target city in a blog
    def test_05_city_mentioned_only_in_blog(self):
        crawled_pages = [
            {
                "url": "https://delhiseofirm.in/blog/our-trip",
                "page_type": "blog",
                "text": "Last week our creative team attended a design conference in Mumbai. We love visiting the Marine Drive.",
            }
        ]
        res = verify_location("Mumbai", "Maharashtra", "India", "", crawled_pages)
        self.assertFalse(res["verified"])
        self.assertIn(res["location_type"], ("service_area", "unverified"))

    # 6. An irrelevant business website
    def test_06_irrelevant_business_website(self):
        dental_clinic_text = "Dr. Sharma Dental Care offers root canal treatments, teeth whitening, and dental implants in Andheri."
        res = classify_industry("Sharma Dental Care", dental_clinic_text, ["Best Dentist in Mumbai"], "Digital Marketing")
        self.assertFalse(res["is_match"])
        self.assertIn("Insufficient industry service evidence", res["rejection_reason"])

        # Training institute exclusion
        training_text = "Join our 3-month digital marketing course with certification. Course syllabus and fees structure available."
        res2 = classify_industry("Apex Digital Academy", training_text, ["Digital Marketing Course and Certification"], "Digital Marketing")
        self.assertFalse(res2["is_match"])

    # 7. A site that requires login
    def test_07_site_requires_login(self):
        is_blocked, reason = detect_anti_bot_or_auth(401, "Authorization Required")
        self.assertTrue(is_blocked)
        self.assertIn("401", reason)

        is_safe, s_reason = is_safe_public_url("ftp://internal.example.com/vault")
        self.assertFalse(is_safe)

    # 8. A URL presenting a CAPTCHA
    def test_08_url_presenting_captcha(self):
        captcha_html = "<html><head><title>Just a moment...</title></head><body><div class='cloudflare-turnstile'>Please verify you are a human</div></body></html>"
        is_blocked, reason = detect_anti_bot_or_auth(200, captcha_html)
        self.assertTrue(is_blocked)
        self.assertIn("CAPTCHA", reason)

    # 9. A site with disallowed robots.txt paths
    @patch("app.services.crawl_policy.is_safe_public_url")
    @patch("requests.get")
    def test_09_disallowed_robots_txt(self, mock_get, mock_safe):
        mock_safe.return_value = (True, "Allowed")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "User-agent: *\nDisallow: /admin/\nDisallow: /restricted/\n"
        mock_get.return_value = mock_resp

        permitted, reason = check_crawl_permission("https://exampleagency.in/restricted/clients")
        self.assertFalse(permitted)
        self.assertIn("robots.txt", reason)

    # 10. A site returning 401 or 403
    def test_10_site_returning_401_or_403(self):
        b401, r401 = detect_anti_bot_or_auth(401, "Unauthorized")
        b403, r403 = detect_anti_bot_or_auth(403, "Forbidden")
        self.assertTrue(b401)
        self.assertTrue(b403)
        self.assertIn("Access Denied", r403)

    # 11. A site returning 429 (Rate limiting)
    def test_11_site_returning_429(self):
        b429, r429 = detect_anti_bot_or_auth(429, "Too Many Requests")
        self.assertTrue(b429)
        self.assertIn("Rate limited", r429)

    # 12. A website with broken or incomplete contact details
    def test_12_broken_or_incomplete_contact_details(self):
        raw_biz = {
            "company_name": "Incomplete Agency",
            "website": "https://incomplete.in",
            "phone": "12345",  # Invalid phone
            "email": "not-an-email",  # Invalid email
        }
        validated = validate_lead(raw_biz)
        self.assertEqual(validated["phone"], "")  # Cleaned, not invented
        self.assertEqual(validated["email"], "")  # Cleaned, not invented
        self.assertEqual(validated["verification_status"], "partial")  # Only website valid

    # 13. Duplicate company domains
    def test_13_duplicate_company_domains(self):
        deduper = IndexedDeduplicator()
        lead1 = {
            "company_name": "Apex Digital",
            "website": "https://apexdigital.in",
            "phone": "+919876543210",
            "email": "",
            "city": "Mumbai",
        }
        lead2 = {
            "company_name": "Apex Digital Marketing",
            "website": "https://www.apexdigital.in/contact",
            "phone": "",
            "email": "contact@apexdigital.in",
            "city": "Mumbai",
        }
        deduper.add_or_merge(lead1)
        deduper.add_or_merge(lead2)
        results = deduper.get_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["phone"], "+919876543210")
        self.assertEqual(results[0]["email"], "contact@apexdigital.in")

    # 14. Interrupted crawl and recovery
    def test_14_interrupted_crawl_and_recovery(self):
        run_id = "test_run_recovery_101"
        create_research_run(run_id, "Digital Marketing", "Mumbai", db_path=self.test_db)
        update_research_run(run_id, execution_status="running", db_path=self.test_db)

        save_checkpoint(
            run_id=run_id,
            stage="urls_discovered",
            last_processed_item="https://apexdigital.in",
            checkpoint_data={"urls_count": 25},
            db_path=self.test_db,
        )

        update_research_run(run_id, execution_status="partially_completed", db_path=self.test_db)

        ckpt = get_latest_checkpoint(run_id, db_path=self.test_db)
        self.assertIsNotNone(ckpt)
        self.assertEqual(ckpt["stage"], "urls_discovered")
        self.assertEqual(ckpt["checkpoint_data"]["urls_count"], 25)

    # 15. Repeated execution without creating duplicate companies
    def test_15_repeated_execution_no_duplicate_companies(self):
        company_data = {
            "company_id": "apex-digital-mumbai",
            "company_name": "Apex Digital",
            "industry_category": "Digital Marketing",
            "city": "Mumbai",
            "state": "Maharashtra",
            "website": "https://apexdigital.in",
            "phone": "+919876543210",
            "email": "hello@apexdigital.in",
        }

        # First insert
        cid1 = save_company(company_data, db_path=self.test_db)
        # Second insert (re-execution)
        cid2 = save_company(company_data, db_path=self.test_db)

        self.assertEqual(cid1, cid2)

        import sqlite3
        conn = sqlite3.connect(self.test_db)
        count = conn.execute("SELECT COUNT(*) FROM companies WHERE company_id = ?", (cid1,)).fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
