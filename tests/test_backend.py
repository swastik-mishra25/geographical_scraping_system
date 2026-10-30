"""Comprehensive unit and mock tests for the optimized backend."""
import json
import os
import unittest
import warnings
from unittest.mock import MagicMock, patch

warnings.filterwarnings("ignore", category=UserWarning, module=r"fastapi(\._compat\.v1)?")

import requests

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
    _discover_alltheplaces,
    _discover_mca_registry,
    _discover_openstreetmap,
    _discover_overture,
    _discover_searxng,
    _discover_wikidata,
    corroborate_candidate_archives,
    discover_businesses,
    discover_businesses_with_stats,
)
from app.services.enrichment import enrich_website, normalize_phone
from app.services.exporter import export_csv
from app.services.pipeline import run_pipeline
from app.services.robots import allowed_by_robots
from app.services.scoring import score_lead
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

    def test_indexed_deduplication_and_merging(self):
        leads = [
            {
                "company_name": "Apex Digital Pvt Ltd",
                "city": "Mumbai",
                "state": "Maharashtra",
                "website": "https://www.apexdigital.in",
                "phone": "+919876543210",
                "email": "",
                "source": "OpenStreetMap",
                "evidence": ["OSM place"],
            },
            {
                "company_name": "Apex Digital",
                "city": "Mumbai",
                "state": "",
                "website": "http://apexdigital.in",
                "phone": "",
                "email": "contact@apexdigital.in",
                "source": "Overture Maps",
                "evidence": ["Overture record"],
            },
            {
                "company_name": "Apex Digital Mumbai",
                "city": "Mumbai",
                "cin": "U72200MH2015PTC123456",
                "website": "",
                "phone": "",
                "email": "",
                "source": "India MCA Company Master Data",
            },
            {
                "company_name": "Beta Media",
                "city": "Delhi",
                "website": "https://betamedia.in",
                "phone": "+919876543222",
                "email": "info@betamedia.in",
                "source": "SearXNG",
            },
        ]
        unique = deduplicate(leads)
        self.assertEqual(len(unique), 2)
        apex = next(l for l in unique if "Apex" in l["company_name"])
        self.assertIn("OpenStreetMap", apex["source"])
        self.assertIn("Overture Maps", apex["source"])
        self.assertEqual(apex["phone"], "+919876543210")
        self.assertEqual(apex["email"], "contact@apexdigital.in")
        self.assertEqual(apex["cin"], "U72200MH2015PTC123456")


class TestContactValidation(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("09876543210"), "+919876543210")
        self.assertEqual(normalize_phone("919876543210"), "+919876543210")
        self.assertEqual(normalize_phone("+91 98765 43210"), "+919876543210")
        self.assertEqual(normalize_phone("12345"), "")
        self.assertEqual(normalize_phone("555-0199"), "")

    def test_validation_logic(self):
        lead = {
            "company_name": "Test Agency",
            "website": "https://testagency.in",
            "phone": "+919876543210",
            "email": "hello@testagency.in",
            "evidence": ["Official website contact confirmed"],
        }
        validated = validate_lead(lead)
        self.assertTrue(validated["_website_valid"])
        self.assertTrue(validated["_phone_valid"])
        self.assertTrue(validated["_email_valid"])
        self.assertIn("website format valid", validated["contact_validation"])
        self.assertIn("+91 Indian phone format valid", validated["contact_validation"])
        self.assertIn("public email format valid", validated["contact_validation"])
        self.assertIn("official website contact confirmed", validated["contact_validation"])

    def test_invalid_contacts_stripped(self):
        lead = {
            "company_name": "Invalid Agency",
            "website": "not a website",
            "phone": "022-2654321",  # Landline, not mobile
            "email": "not-an-email",
        }
        validated = validate_lead(lead)
        self.assertFalse(validated["_website_valid"])
        self.assertFalse(validated["_phone_valid"])
        self.assertFalse(validated["_email_valid"])
        self.assertEqual(validated["phone"], "")
        self.assertEqual(validated["email"], "")
        self.assertIn("no validated contact found", validated["contact_validation"])


class TestScoring(unittest.TestCase):
    def test_scoring_weights_preserved(self):
        lead = {
            "company_name": "Zenith Digital Marketing Agency",
            "sector": "Digital Marketing",
            "city": "Mumbai",
            "_website_valid": True,
            "_phone_valid": True,
            "_email_valid": True,
        }
        score, reason = score_lead(lead)
        self.assertEqual(score, 100)
        self.assertIn("website available", reason)
        self.assertIn("valid Indian business phone", reason)
        self.assertIn("public business email", reason)
        self.assertIn("marketing relevance", reason)
        self.assertIn("geographic match", reason)

        lead2 = {
            "company_name": "Zenith Creative",
            "sector": "Digital Marketing",
            "city": "Pune",
            "_website_valid": True,
            "_phone_valid": False,
            "_email_valid": False,
        }
        score2, reason2 = score_lead(lead2)
        self.assertEqual(score2, 60)


class TestSourceAdapters(unittest.TestCase):
    @patch("requests.post")
    @patch("app.services.discovery.get_city_bounds")
    def test_osm_adapter_success(self, mock_bounds, mock_post):
        mock_bounds.return_value = (19.0, 72.8, 19.2, 73.0, "Maharashtra")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {
                    "tags": {
                        "name": "OSM Digital Media",
                        "office": "advertising_agency",
                        "website": "https://osm-media.in",
                        "phone": "+919876543210",
                        "email": "contact@osm-media.in",
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        recs, raw, err, dur = _discover_openstreetmap("Mumbai", "Maharashtra", "Digital Marketing", 10)
        self.assertIsNone(err)
        self.assertEqual(raw, 1)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["company_name"], "OSM Digital Media")

    @patch("requests.get")
    def test_searxng_fallback_handling(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        recs, raw, err, note, dur = _discover_searxng("Mumbai", "Maharashtra", "Digital Marketing", 10)
        # Should gracefully report or fallback without crashing
        self.assertIn("Web Search", note)

    @patch("requests.get")
    def test_wikidata_adapter(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "results": {
                "bindings": [
                    {
                        "itemLabel": {"value": "Dentsu India"},
                        "desc": {"value": "advertising agency in Mumbai"},
                        "website": {"value": "https://dentsu.in"},
                        "cityLabel": {"value": "Mumbai"},
                    }
                ]
            }
        }
        mock_get.return_value = mock_resp

        recs, raw, err, note, dur = _discover_wikidata("Mumbai", "Maharashtra", "Digital Marketing", 10)
        self.assertIsNone(err)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["company_name"], "Dentsu India")

    def test_mca_dataset_loading(self):
        recs, raw, err, note, dur = _discover_mca_registry("Bhubaneswar", "Odisha", "Digital Marketing", 10)
        self.assertIsNone(err)
        self.assertGreaterEqual(len(recs), 1)
        self.assertTrue(any("Addzet" in r["company_name"] or "Shadow" in r["company_name"] for r in recs))
        self.assertTrue(recs[0]["cin"].startswith("U"))

    def test_alltheplaces_dataset_loading(self):
        recs, raw, err, note, dur = _discover_alltheplaces("Bhubaneswar", "Odisha", "Digital Marketing", 10)
        self.assertIsNone(err)
        self.assertGreaterEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "AllThePlaces")

    @patch("requests.get")
    def test_wayback_archive_corroboration(self, mock_get):
        mock_cdx = MagicMock()
        mock_cdx.ok = True
        mock_cdx.json.return_value = [
            ["timestamp", "original"],
            ["20210515120000", "https://example.in/"]
        ]
        mock_get.return_value = mock_cdx

        candidates = [{"company_name": "Example Corp", "website": "https://example.in"}]
        checked, matched, note = corroborate_candidate_archives(candidates, max_checks=1)
        self.assertEqual(checked, 1)
        self.assertEqual(matched, 1)
        self.assertIn("Web archive corroborated", candidates[0]["evidence"][0])


class TestEndToEndPipelineMocked(unittest.TestCase):
    @patch("app.services.pipeline.time.sleep")
    @patch("app.services.pipeline.discover_businesses_with_stats")
    @patch("app.services.pipeline.enrich_website")
    def test_run_pipeline_contract_and_scale(self, mock_enrich, mock_discover, mock_sleep):
        mock_discover.return_value = DiscoveryResult(
            businesses=[
                {
                    "company_name": f"Agency {i}",
                    "sector": "Digital Marketing",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "website": f"https://agency{i}.in",
                    "phone": f"+919876543{i:03d}",
                    "email": f"info@agency{i}.in",
                    "source": "OpenStreetMap",
                    "_location_verified": True,
                }
                for i in range(1, 250)  # > 200 items to verify no 200-cap!
            ],
            source_stats={"OpenStreetMap": {"raw": 249, "unique": 249, "status": "ok"}},
            notes=[],
        )
        mock_enrich.return_value = {
            "phone": "+919876543210",
            "email": "info@example.in",
            "title": "Agency - Digital Marketing",
            "evidence": ["Public homepage inspected"],
            "robots_status": "robots.txt permits access",
            "website_verified": True,
        }

        # Request limit=240 (> 200!)
        result = run_pipeline(city="TestCity", category="Digital Marketing", limit=240)
        self.assertEqual(result["requested_city"], "TestCity")
        self.assertEqual(result["requested_category"], "Digital Marketing")
        self.assertGreaterEqual(result["discovered"], 240)
        self.assertGreaterEqual(result["qualified"], 240)
        self.assertEqual(len(result["leads"]), 240)
        self.assertTrue(os.path.exists(result["csv_file"]))

        # Cleanup test CSV artifact
        if os.path.exists(result["csv_file"]):
            try:
                os.remove(result["csv_file"])
            except Exception:
                pass

        lead = result["leads"][0]
        validated_lead = Lead(**lead)
        self.assertEqual(validated_lead.lead_quality_score, 100)


if __name__ == "__main__":
    unittest.main()
