"""Unit tests for AI-powered business data extraction (ExtractedBusinessProfile & fallback)."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.extraction import (
    ExtractedBusinessProfile,
    _extract_with_ai,
    extract_business_data,
)


class TestExtractedBusinessProfileSchema(unittest.TestCase):
    def test_valid_pydantic_schema(self):
        raw = {
            "official_business_name": "Apex Digital Pvt Ltd",
            "decision_makers": [{"name": "Rahul Verma", "role": "Founder & CEO"}],
            "direct_phones": ["+919876543210"],
            "verified_emails": ["info@apexdigital.in"],
            "year_founded": 2018,
            "team_size_bracket": "11-50",
            "primary_services": ["SEO", "Performance Marketing"],
            "physical_address": {
                "city": "Mumbai",
                "state": "Maharashtra",
                "locality": "Andheri West",
                "pin": "400053",
            },
        }
        profile = ExtractedBusinessProfile(**raw)
        self.assertEqual(profile.official_business_name, "Apex Digital Pvt Ltd")
        self.assertEqual(profile.year_founded, 2018)
        self.assertEqual(profile.decision_makers[0]["name"], "Rahul Verma")
        self.assertEqual(profile.physical_address["pin"], "400053")

    def test_schema_handles_nulls_and_invalid_years(self):
        raw = {
            "official_business_name": None,
            "decision_makers": None,
            "direct_phones": None,
            "verified_emails": None,
            "year_founded": "invalid_year",
            "team_size_bracket": None,
            "primary_services": None,
            "physical_address": None,
        }
        profile = ExtractedBusinessProfile(**raw)
        self.assertEqual(profile.official_business_name, "")
        self.assertEqual(profile.decision_makers, [])
        self.assertIsNone(profile.year_founded)


class TestAIExtractionAndWildFailureCases(unittest.TestCase):
    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"})
    @patch("app.services.extraction.requests.post")
    def test_ai_extraction_obfuscated_email_and_whatsapp(self, mock_post):
        ai_json = {
            "official_business_name": "GrowthPulse Media",
            "decision_makers": [{"name": "Priya Nair", "role": "CEO"}],
            "direct_phones": ["919876543210"],
            "verified_emails": ["info [at] growthpulse [dot] in"],
            "year_founded": 2019,
            "team_size_bracket": "11-50",
            "primary_services": ["Performance Marketing", "SEO"],
            "physical_address": {
                "city": "Mumbai",
                "state": "Maharashtra",
                "locality": "Bandra West",
                "pin": "400050",
            },
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": json.dumps(ai_json)}]}}]
        }
        mock_post.return_value = mock_resp

        pages = [
            {
                "url": "https://growthpulse.in/contact",
                "page_type": "contact",
                "title": "Contact GrowthPulse",
                "text": "Reach us at info [at] growthpulse [dot] in or https://wa.me/919876543210. Founded in 2019.",
                "soup": None,
            }
        ]

        data = extract_business_data("https://growthpulse.in", pages, city="Mumbai", state="Maharashtra")
        self.assertEqual(data["company_name"], "GrowthPulse Media")
        self.assertEqual(data["phone"], "+919876543210")
        self.assertTrue(data["has_phone"])
        self.assertEqual(data["email"], "info@growthpulse.in")
        self.assertEqual(data["contact_person"], "Priya Nair")
        self.assertEqual(data["contact_role"], "CEO")
        self.assertEqual(data["company_age"], "Founded 2019")
        self.assertEqual(data["company_size"], "11-50")
        self.assertEqual(data["locality"], "Bandra West")
        self.assertEqual(data["services"], ["Performance Marketing", "SEO"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"})
    @patch("app.services.extraction.requests.post")
    def test_copyright_year_not_mistaken_for_year_founded(self, mock_post):
        # Even if AI mistakenly returns 2026 from a copyright footer, the copyright guard rejects it
        ai_json = {
            "official_business_name": "Pixel Studio",
            "decision_makers": [],
            "direct_phones": [],
            "verified_emails": [],
            "year_founded": 2026,
            "team_size_bracket": "unknown",
            "primary_services": [],
            "physical_address": None,
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": json.dumps(ai_json)}]}}]
        }
        mock_post.return_value = mock_resp

        pages = [
            {
                "url": "https://pixelstudio.in",
                "page_type": "homepage",
                "title": "Pixel Studio",
                "text": "Welcome to Pixel Studio. © 2026 Pixel Studio. All rights reserved.",
                "soup": None,
            }
        ]
        data = extract_business_data("https://pixelstudio.in", pages)
        self.assertEqual(data["company_age"], "unknown")

    def test_fallback_handles_steve_jobs_false_positive_and_obfuscated_email(self):
        # Without AI key (fallback mode), verify regex improvements handle the 4 wild cases
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            pages = [
                {
                    "url": "https://novaagency.in/about",
                    "page_type": "about",
                    "title": "Nova Agency",
                    "text": (
                        "Our founder was inspired by Steve Jobs to build great products. "
                        "Today our CEO Rahul Verma leads the agency. "
                        "Contact us at info [at] novaagency [dot] in or https://wa.me/919876543210. "
                        "© 2026 Nova Agency."
                    ),
                    "soup": None,
                }
            ]
            data = extract_business_data("https://novaagency.in", pages)
            self.assertEqual(data["email"], "info@novaagency.in")
            self.assertEqual(data["phone"], "+919876543210")
            self.assertEqual(data["contact_person"], "Rahul Verma")
            self.assertNotEqual(data["contact_person"], "Steve Jobs")
            self.assertEqual(data["company_age"], "unknown")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"})
    @patch("app.services.extraction.requests.post")
    def test_ai_api_failure_falls_back_to_regex(self, mock_post):
        mock_post.side_effect = RuntimeError("API timeout / connection error")

        pages = [
            {
                "url": "https://fallbackagency.in/contact",
                "page_type": "contact",
                "title": "Fallback Agency",
                "text": "Call us: +91 987 654 3210 | Email: contact@fallbackagency.in | Founded in 2015",
                "soup": None,
            }
        ]
        data = extract_business_data("https://fallbackagency.in", pages)
        self.assertEqual(data["phone"], "+919876543210")
        self.assertEqual(data["email"], "contact@fallbackagency.in")
        self.assertEqual(data["company_age"], "Founded 2015")


if __name__ == "__main__":
    unittest.main()
