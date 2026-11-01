"""Comprehensive unit and mock tests for the optimized autonomous backend."""
import json
import os
import unittest
import warnings
from unittest.mock import MagicMock, patch

import requests

warnings.filterwarnings("ignore", category=UserWarning, module=r"fastapi(\._compat\.v1)?")

from app.models import Lead, ScrapeRequest, ScrapeResponse
from app.services.dedupe import (
    IndexedDeduplicator,
    deduplicate,
    domain,
    normalize_cin,
    normalize_name,
)
from app.services.discovery import (
    DiscoveryResult,
    discover_businesses,
    discover_businesses_with_stats,
    get_city_bounds,
)
from app.services.exporter import export_csv
from app.services.industry_classifier import classify_industry
from app.services.location_verifier import verify_location
from app.services.pipeline import run_pipeline
from app.services.public_web_discovery import PublicWebDiscoveryGateway
from app.services.query_generator import generate_discovery_queries
from app.services.robots import allowed_by_robots, _ROBOTS_CACHE
from app.services.scoring import score_lead
from app.services.url_frontier import calculate_url_priority, normalize_url
from app.services.validation import validate_lead


class TestDeduplication(unittest.TestCase):
    def test_domain_normalization(self):
        self.assertEqual(domain("https://www.example.com/path"), "example.com")
        self.assertEqual(domain("http://example.com:8080"), "example.com")
        self.assertEqual(domain("example.com"), "example.com")
        # Social media & directory domains rejected
        self.assertEqual(domain("https://facebook.com/company"), "")
        self.assertEqual(domain("https://www.justdial.com/page"), "")
        self.assertEqual(domain(""), "")

    def test_name_normalization(self):
        self.assertEqual(normalize_name("Acme Marketing Pvt Ltd"), "acmemarketing")
        self.assertEqual(normalize_name("Global Tech LLP"), "globaltech")
        self.assertEqual(normalize_name("Alpha & Omega Media, Inc."), "alphaomegamedia")
        # With city context stripped
        self.assertEqual(normalize_name("Apex Digital Mumbai", "Mumbai"), "apexdigital")

    def test_cin_normalization(self):
        valid_cin = "U72200MH2010PTC200000"
        self.assertEqual(normalize_cin(valid_cin), valid_cin)
        self.assertEqual(normalize_cin("invalid"), "")

    def test_indexed_deduplicator(self):
        deduper = IndexedDeduplicator()
        lead1 = {
            "company_name": "Apex Digital",
            "city": "Mumbai",
            "website": "https://apexdigital.in",
            "phone": "+919876543210",
            "email": "",
            "source": "Public Web",
            "evidence": ["Public record 1"],
        }
        lead2 = {
            "company_name": "Apex Digital Marketing",
            "city": "Mumbai",
            "website": "https://www.apexdigital.in/about",
            "phone": "",
            "email": "contact@apexdigital.in",
            "source": "Website Crawl",
            "evidence": ["Crawl record 2"],
        }
        deduper.add_or_merge(lead1)
        deduper.add_or_merge(lead2)
        results = deduper.get_results()

        self.assertEqual(len(results), 1)
        merged = results[0]
        self.assertEqual(merged["phone"], "+919876543210")
        self.assertEqual(merged["email"], "contact@apexdigital.in")
        self.assertIn("Public Web", merged["source"])
        self.assertIn("Website Crawl", merged["source"])
        self.assertEqual(len(merged["evidence"]), 2)


class TestContactValidation(unittest.TestCase):
    def test_phone_normalization(self):
        from app.services.extraction import normalize_indian_phone
        self.assertEqual(normalize_indian_phone("09876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("919876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("+91 98765 43210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("9876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("12345"), "")

    def test_lead_validation_clean_contact(self):
        lead = {
            "company_name": "Valid Agency",
            "website": "https://validagency.in",
            "phone": "+919876543210",
            "email": "hello@validagency.in",
            "evidence": ["Official website contact confirmed"],
        }
        validated = validate_lead(lead)
        self.assertTrue(validated["_website_valid"])
        self.assertTrue(validated["_phone_valid"])
        self.assertTrue(validated["_email_valid"])
        self.assertIn("+91 Indian phone format valid", validated["contact_validation"])
        self.assertIn("public email format valid", validated["contact_validation"])
        self.assertEqual(validated["verification_status"], "verified")


class TestScoringModelPreserved(unittest.TestCase):
    def test_scoring_weights(self):
        # Verification that historical scoring model formula remains preserved
        full_lead = {
            "company_name": "Apex Marketing",
            "sector": "Digital Marketing",
            "city": "Mumbai",
            "website": "https://example.in",
            "phone": "+919876543210",
            "email": "contact@example.in",
        }
        full_lead = validate_lead(full_lead)
        score, reason = score_lead(full_lead)
        self.assertEqual(score, 100)

        partial_lead = {
            "company_name": "Apex Marketing",
            "sector": "Digital Marketing",
            "website": "https://example.in",
            "phone": "+919876543210",
            "email": "",
        }
        partial_lead = validate_lead(partial_lead)
        score2, reason2 = score_lead(partial_lead)
        self.assertEqual(score2, 75)


class TestRobotsPoliteness(unittest.TestCase):
    def setUp(self):
        _ROBOTS_CACHE.clear()

    @patch("requests.get")
    def test_robots_disallow(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "User-agent: *\nDisallow: /private/\n"
        mock_get.return_value = mock_resp

        allowed, status = allowed_by_robots("https://testdomain.in/private/secret")
        self.assertFalse(allowed)
        self.assertIn("does not permit", status)

    @patch("requests.get")
    def test_robots_allow(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "User-agent: *\nAllow: /\n"
        mock_get.return_value = mock_resp

        allowed, status = allowed_by_robots("https://testdomain.in/contact")
        self.assertTrue(allowed)
        self.assertIn("permits access", status)

    @patch("requests.get")
    def test_robots_failure_graceful(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("Connection timeout")
        # On connection failure, policy fails open safely
        allowed, status = allowed_by_robots("https://testdomain.in/homepage")
        self.assertTrue(allowed)


class TestDiscoveryAndCrawlingArchitecture(unittest.TestCase):
    def test_query_generator_expansion(self):
        queries = generate_discovery_queries("Digital Marketing", city="Kolkata", state="West Bengal")
        self.assertGreaterEqual(len(queries), 3)
        self.assertTrue(any("kolkata" in q["query"].lower() for q in queries))

    def test_frontier_url_prioritization(self):
        self.assertEqual(calculate_url_priority("https://agency.in/"), 100)
        self.assertEqual(calculate_url_priority("https://agency.in/contact-us"), 95)
        self.assertEqual(calculate_url_priority("https://agency.in/about-us"), 85)
        self.assertEqual(calculate_url_priority("https://agency.in/services"), 80)
        self.assertEqual(calculate_url_priority("https://agency.in/blog/post-1"), 50)

    def test_industry_classification_digital_marketing(self):
        text = "We are a full-service digital marketing agency in Mumbai offering SEO, Google Ads, and Performance Marketing."
        res = classify_industry("Apex Media", text, ["Digital Marketing Agency Mumbai"], "Digital Marketing")
        self.assertTrue(res["is_match"])
        self.assertEqual(res["industry_category"], "Digital Marketing")

    def test_location_verifier_hq_vs_branch(self):
        pages_hq = [{"url": "https://a.in/c", "page_type": "contact", "text": "Head Office: Nariman Point, Mumbai 400021"}]
        res_hq = verify_location("Mumbai", "Maharashtra", "India", "", pages_hq)
        self.assertTrue(res_hq["verified"])
        self.assertEqual(res_hq["location_type"], "headquarters")

        pages_branch = [{"url": "https://a.in/c", "page_type": "contact", "text": "Our Branch Office: MG Road, Bengaluru 560001"}]
        res_branch = verify_location("Bengaluru", "Karnataka", "India", "", pages_branch)
        self.assertTrue(res_branch["verified"])
        self.assertEqual(res_branch["location_type"], "branch")


class TestEndToEndPipelineMocked(unittest.TestCase):
    @patch("app.services.orchestrator.PublicWebDiscoveryGateway.run_discovery")
    @patch("app.services.orchestrator.crawl_website")
    def test_run_pipeline_contract_and_scale(self, mock_crawl, mock_discovery):
        mock_discovery.return_value = [
            {"url": f"https://agency{i}.in", "domain": f"agency{i}.in", "query": "SEO Mumbai", "method": "test"}
            for i in range(1, 26)
        ]

        def _fake_crawl(url, max_pages=2):
            return {
                "root_url": url,
                "domain": url.replace("https://", ""),
                "status": "completed",
                "crawled_pages": [
                    {
                        "url": f"{url}/contact",
                        "page_type": "contact",
                        "title": "Creative Agency - Digital Marketing",
                        "text": f"Creative Agency is an SEO and Performance Marketing company in Mumbai. Headquarters: Andheri East, Mumbai 400069. Ph: +919876543000 Email: info@{url.replace('https://', '')}",
                        "soup": None,
                    }
                ],
                "combined_text": "SEO performance marketing company in Mumbai Headquarters: Andheri East, Mumbai 400069. Ph: +919876543000",
                "page_titles": ["Creative Agency - Digital Marketing"],
            }

        mock_crawl.side_effect = _fake_crawl

        result = run_pipeline(city="Mumbai", category="Digital Marketing", limit=20)
        self.assertEqual(result["requested_city"], "Mumbai")
        self.assertEqual(result["requested_category"], "Digital Marketing")
        self.assertGreaterEqual(result["discovered"], 20)
        self.assertGreaterEqual(result["qualified"], 1)
        self.assertTrue(os.path.exists(result["csv_file"]))

        # Cleanup test CSV artifact
        if os.path.exists(result["csv_file"]):
            try:
                os.remove(result["csv_file"])
            except Exception:
                pass

        lead = result["leads"][0]
        validated_lead = Lead(**lead)
        self.assertEqual(validated_lead.city, "Mumbai")
        self.assertEqual(validated_lead.lead_quality_score, 0)  # Verifies ICP scoring was NOT invoked!


if __name__ == "__main__":
    unittest.main()
