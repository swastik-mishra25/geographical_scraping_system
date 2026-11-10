"""Unit tests for phone number extraction, normalization, validation, and filtering."""
import unittest
from bs4 import BeautifulSoup

from app.services.extraction import (
    PHONE_RE,
    extract_business_data,
    normalize_indian_phone,
)
from app.services.validation import (
    INDIAN_MOBILE_RE,
    INDIAN_LANDLINE_RE,
    INDIAN_TOLLFREE_RE,
    INDIAN_PHONE_RE,
    validate_lead,
)
from app.services.persistence import (
    get_companies_with_phone,
    get_phone_stats,
)
from app.services.orchestrator import execute_autonomous_run


class TestPhoneNormalization(unittest.TestCase):
    def test_mobile_normalization(self):
        # 10 digits starting with 6,7,8,9
        self.assertEqual(normalize_indian_phone("+919876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("9876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("09876543210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("+91 98765-43210"), "+919876543210")
        self.assertEqual(normalize_indian_phone("(+91) 98765 43210"), "+919876543210")

    def test_landline_normalization(self):
        # 2-digit STD: Mumbai (022), Delhi (011)
        self.assertEqual(normalize_indian_phone("02226834100"), "+912226834100")
        self.assertEqual(normalize_indian_phone("+91-22-2683-4100"), "+912226834100")
        self.assertEqual(normalize_indian_phone("01141551234"), "+911141551234")

        # 3-digit STD: Bhubaneswar (0674)
        self.assertEqual(normalize_indian_phone("06742541234"), "+916742541234")
        self.assertEqual(normalize_indian_phone("+91 674 254 1234"), "+916742541234")

    def test_tollfree_normalization(self):
        self.assertEqual(normalize_indian_phone("18001234567"), "+9118001234567")
        self.assertEqual(normalize_indian_phone("+91 1800 123 4567"), "+9118001234567")

    def test_invalid_phones(self):
        self.assertEqual(normalize_indian_phone("12345"), "")
        self.assertEqual(normalize_indian_phone("invalid_string"), "")
        self.assertEqual(normalize_indian_phone(""), "")


class TestPhoneValidation(unittest.TestCase):
    def test_mobile_validation(self):
        lead = {"website": "https://example.com", "phone": "+919876543210"}
        validated = validate_lead(lead)
        self.assertTrue(validated["_phone_valid"])
        self.assertTrue(validated["has_phone"])
        self.assertEqual(validated["phone_type"], "mobile")
        self.assertEqual(validated["phone"], "+919876543210")

    def test_landline_validation(self):
        lead = {"website": "https://example.com", "phone": "+912226834100"}
        validated = validate_lead(lead)
        self.assertTrue(validated["_phone_valid"])
        self.assertTrue(validated["has_phone"])
        self.assertEqual(validated["phone_type"], "landline")
        self.assertEqual(validated["phone"], "+912226834100")

    def test_tollfree_validation(self):
        lead = {"website": "https://example.com", "phone": "+9118001234567"}
        validated = validate_lead(lead)
        self.assertTrue(validated["_phone_valid"])
        self.assertTrue(validated["has_phone"])
        self.assertEqual(validated["phone_type"], "toll_free")

    def test_invalid_phone_cleared(self):
        lead = {"website": "https://example.com", "phone": "12345"}
        validated = validate_lead(lead)
        self.assertFalse(validated["_phone_valid"])
        self.assertFalse(validated["has_phone"])
        self.assertEqual(validated["phone"], "")
        self.assertEqual(validated["_raw_phone"], "12345")


class TestPhoneExtraction(unittest.TestCase):
    def test_extract_tel_link(self):
        html = '<a href="tel:+919876543210">Call Us</a>'
        soup = BeautifulSoup(html, "html.parser")
        pages = [{"url": "https://agency.in", "page_type": "contact", "text": "Contact", "soup": soup}]
        data = extract_business_data("https://agency.in", pages)
        self.assertEqual(data["phone"], "+919876543210")
        self.assertTrue(data["has_phone"])

    def test_extract_whatsapp_link(self):
        html = '<a href="https://wa.me/919876543210?text=Hi">Chat with us on WhatsApp</a>'
        soup = BeautifulSoup(html, "html.parser")
        pages = [{"url": "https://agency.in", "page_type": "contact", "text": "WhatsApp", "soup": soup}]
        data = extract_business_data("https://agency.in", pages)
        self.assertEqual(data["phone"], "+919876543210")
        self.assertTrue(data["has_phone"])

    def test_extract_schema_json_ld(self):
        html = '''
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": "Super Agency",
            "telephone": "+91 (022) 2683-4100"
        }
        </script>
        '''
        soup = BeautifulSoup(html, "html.parser")
        pages = [{"url": "https://agency.in", "page_type": "homepage", "text": "Super Agency", "soup": soup}]
        data = extract_business_data("https://agency.in", pages)
        self.assertEqual(data["phone"], "+912226834100")
        self.assertTrue(data["has_phone"])

    def test_extract_microdata_itemprop(self):
        html = '<span itemprop="telephone">+91 98765 43210</span>'
        soup = BeautifulSoup(html, "html.parser")
        pages = [{"url": "https://agency.in", "page_type": "contact", "text": "Phone", "soup": soup}]
        data = extract_business_data("https://agency.in", pages)
        self.assertEqual(data["phone"], "+919876543210")
        self.assertTrue(data["has_phone"])

    def test_extract_labeled_text(self):
        pages = [{
            "url": "https://agency.in",
            "page_type": "contact",
            "text": "For business inquiries, reach our team: Phone: +91 674 254 1234 or Email: info@agency.in",
            "soup": None
        }]
        data = extract_business_data("https://agency.in", pages)
        self.assertEqual(data["phone"], "+916742541234")
        self.assertTrue(data["has_phone"])


class TestPhoneFilteringInOrchestrator(unittest.TestCase):
    def test_phone_required_run(self):
        res = execute_autonomous_run(city="Bhubaneswar", limit=20, phone_required=True)
        self.assertTrue(res["qualified"] > 0)
        self.assertTrue(res["leads_with_phone"] > 0)
        # Every returned lead must have a phone number
        for lead in res["leads"]:
            self.assertTrue(bool(lead.get("phone")), f"Lead {lead.get('company_name')} missing phone!")
            self.assertTrue(lead.get("phone").startswith("+91"))


class TestPhoneDatabaseOperations(unittest.TestCase):
    def test_get_companies_with_phone(self):
        leads = get_companies_with_phone(limit=10)
        self.assertTrue(len(leads) > 0)
        for lead in leads:
            self.assertTrue(bool(lead["phone"]))

    def test_get_phone_stats(self):
        stats = get_phone_stats()
        self.assertIn("total_companies", stats)
        self.assertIn("with_phone", stats)
        self.assertGreater(stats["with_phone"], 0)
        self.assertGreaterEqual(stats["phone_coverage_pct"], 90.0)


if __name__ == "__main__":
    unittest.main()

