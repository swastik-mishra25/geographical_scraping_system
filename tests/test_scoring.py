"""Unit tests for Stage 9: 100-Point Ideal Customer Profile (ICP) Lead Quality Scorer."""
from __future__ import annotations

import unittest
from typing import Any

from app.services.scoring import score_lead


class TestLeadQualityScorer(unittest.TestCase):
    def test_empty_or_invalid_lead(self):
        score, reason = score_lead({})
        self.assertEqual(score, 0)
        self.assertIn("no lead data", reason)

        score_none, reason_none = score_lead(None)  # type: ignore
        self.assertEqual(score_none, 0)

        score_str, _ = score_lead("invalid")  # type: ignore
        self.assertEqual(score_str, 0)

    def test_pillar_1_contact_reachability_mobile(self):
        lead = {
            "phone": "+919876543210",
            "phone_type": "mobile",
            "email": "info@agency.in",
            "website": "https://agency.in",
        }
        score, reason = score_lead(lead)
        # Mobile (+20) + Email (+10) + Website (+5) = 35
        # plus core digital marketing (+12) from default category
        self.assertIn("direct mobile phone (+20)", reason)
        self.assertIn("business email (+10)", reason)
        self.assertIn("verified domain (+5)", reason)
        self.assertGreaterEqual(score, 35)

    def test_pillar_1_contact_reachability_landline(self):
        lead = {
            "phone": "+911122334455",
            "phone_type": "landline",
            "email": "",
            "website": "https://corp.in",
        }
        score, reason = score_lead(lead)
        # Landline (+15) + Website (+5) = 20
        self.assertIn("corporate landline (+15)", reason)
        self.assertIn("verified domain (+5)", reason)

    def test_pillar_1_contact_reachability_toll_free(self):
        lead = {
            "phone": "1800123456",
            "_phone_valid": True,
            "phone_type": "toll_free",
        }
        score, reason = score_lead(lead)
        self.assertIn("toll-free line (+10)", reason)

    def test_pillar_2_geographic_grounding_hq_and_pin(self):
        lead = {
            "location_type": "headquarters",
            "city": "Bengaluru",
            "address": "Tower 4, Electronic City, Bengaluru 560100",
        }
        score, reason = score_lead(lead)
        # HQ (+15) + PIN/Address grounded (+10) = 25
        self.assertIn("registered headquarters (+15)", reason)
        self.assertIn("street address / PIN grounded (+10)", reason)
        self.assertGreaterEqual(score, 25)

    def test_pillar_2_geographic_grounding_branch_and_locality(self):
        lead = {
            "location_type": "branch",
            "city": "Pune",
            "locality": "Hinjewadi",
        }
        score, reason = score_lead(lead)
        # Branch (+10) + Locality (+5) = 15
        self.assertIn("regional branch office (+10)", reason)
        self.assertIn("commercial locality grounded: Hinjewadi (+5)", reason)

    def test_pillar_3_industry_relevance_across_categories(self):
        # Healthcare test
        health_lead = {
            "company_name": "Apollo Multispeciality Hospitals",
            "sector": "Healthcare",
            "industry_subcategory": "Hospital & Surgery Center",
            "services": ["Cardiology Care", "Diagnostic Imaging"],
        }
        score, reason = score_lead(health_lead, target_category="Healthcare")
        self.assertIn("core healthcare match (+12)", reason)
        self.assertIn("specialized service catalog (+8)", reason)
        # Pillar 3 = 12 + 8 = 20
        self.assertEqual(score, 20)

        # Real Estate test
        re_lead = {
            "company_name": "Prestige Properties & Estates",
            "sector": "Real Estate",
            "services": ["Commercial Property Leasing"],
        }
        score_re, reason_re = score_lead(re_lead, target_category="Real Estate")
        self.assertIn("core real estate match (+12)", reason_re)
        self.assertIn("basic service listed (+4)", reason_re)

    def test_pillar_4_business_authority(self):
        lead = {
            "contact_person": "Pooja Hegde",
            "contact_role": "Chief Executive Officer",
            "cin": "U72200KA2020PTC134567",
            "company_size": "50-200 employees",
            "evidence": ["Excerpt proof 1", "Excerpt proof 2"],
        }
        score, reason = score_lead(lead)
        # Decision maker (+10) + MCA CIN (+5) + 2 proofs (+5) = 20
        self.assertIn("decision-maker identified: Pooja Hegde (Chief Executive Officer) (+10)", reason)
        self.assertIn("verified MCA registered entity (+5)", reason)
        self.assertIn("2 verified audit proofs (+5)", reason)
        self.assertGreaterEqual(score, 20)

    def test_perfect_100_lead(self):
        lead = {
            # Pillar 1 (35 pts)
            "phone": "+919876543210",
            "phone_type": "mobile",
            "email": "director@nexusmedia.in",
            "website": "https://nexusmedia.in",
            # Pillar 2 (25 pts)
            "city": "Mumbai",
            "location_type": "headquarters",
            "address": "Floor 7, Trade Centre, BKC, Mumbai 400051",
            "locality": "Bandra Kurla Complex",
            # Pillar 3 (20 pts)
            "company_name": "Nexus Media & Digital Solutions",
            "sector": "Digital Marketing",
            "industry_subcategory": "Performance Marketing & SEO",
            "services": ["Search Engine Optimization", "Social Media Campaigns"],
            # Pillar 4 (20 pts)
            "contact_person": "Aditya Verma",
            "contact_role": "Managing Director",
            "cin": "U74300MH2016PTC284901",
            "evidence": [
                {"evidence_excerpt": "Corporate office at BKC Mumbai 400051"},
                {"evidence_excerpt": "Founded by Managing Director Aditya Verma"},
            ],
        }
        score, reason = score_lead(lead, target_category="Digital Marketing")
        self.assertEqual(score, 100)
        # Verify all 4 pillars are justified in audit reason
        self.assertIn("direct mobile phone (+20)", reason)
        self.assertIn("business email (+10)", reason)
        self.assertIn("verified domain (+5)", reason)
        self.assertIn("registered headquarters (+15)", reason)
        self.assertIn("street address / PIN grounded (+10)", reason)
        self.assertIn("core digital marketing match (+12)", reason)
        self.assertIn("specialized service catalog (+8)", reason)
        self.assertIn("decision-maker identified: Aditya Verma (Managing Director) (+10)", reason)
        self.assertIn("verified MCA registered entity (+5)", reason)
        self.assertIn("2 verified audit proofs (+5)", reason)

    def test_zero_overflow_guarantee(self):
        # Over-saturated lead with redundant signals in each pillar
        over_lead = {
            "phone": "+919876543210",
            "phone_type": "mobile",
            "_phone_valid": True,
            "email": "admin@mega.in",
            "_email_valid": True,
            "website": "https://mega.in",
            "_website_valid": True,
            "city": "Delhi",
            "location_type": "headquarters",
            "address": "Connaught Place, New Delhi 110001, Building 5, Floor 3",
            "locality": "Connaught Place",
            "company_name": "Mega Digital Marketing & Media Private Limited",
            "sector": "Digital Marketing",
            "industry_subcategory": "Comprehensive Digital & SEO Services",
            "services": ["SEO", "PPC", "Social Media", "Content", "Web Dev"],
            "contact_person": "Rajesh Kumar",
            "contact_role": "Chief Executive Officer & Founder",
            "cin": "U72900DL2015PTC123456",
            "company_age": "9 years",
            "company_size": "250+ employees",
            "evidence": ["proof 1", "proof 2", "proof 3", "proof 4"],
        }
        score, _ = score_lead(over_lead, target_category="Digital Marketing")
        self.assertEqual(score, 100)
        self.assertLessEqual(score, 100)


if __name__ == "__main__":
    unittest.main()
