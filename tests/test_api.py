"""API endpoint unit tests using existing framework and dependencies."""
import os
import unittest
import warnings
from unittest.mock import MagicMock, patch
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module=r"fastapi(\._compat\.v1)?")

from fastapi.responses import FileResponse
from fastapi import HTTPException

from app.main import app, download_csv, health, home, scrape
from app.models import ScrapeRequest, ScrapeResponse


class TestAPIEndpoints(unittest.TestCase):
    def test_health_check(self):
        resp = health()
        self.assertEqual(resp, {"status": "ok"})

    def test_home_page(self):
        resp = home()
        self.assertIsInstance(resp, FileResponse)
        path = Path(resp.path)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "index.html")
        content = path.read_text(encoding="utf-8")
        self.assertIn("Geographical Lead Scraping POC", content)
        # Ensure static UI remains unchanged
        self.assertIn('id="city"', content)
        self.assertIn('id="state"', content)
        self.assertIn('id="category"', content)
        self.assertIn('id="limit"', content)

    @patch("app.main.run_pipeline")
    def test_scrape_endpoint_success(self, mock_pipeline):
        mock_pipeline.return_value = {
            "requested_city": "Bhubaneswar",
            "requested_category": "Digital Marketing",
            "discovered": 10,
            "qualified": 2,
            "leads": [
                {
                    "company_name": "Creative Agency 1",
                    "sector": "Digital Marketing",
                    "city": "Bhubaneswar",
                    "state": "Odisha",
                    "website": "https://agency1.in",
                    "phone": "+919876543210",
                    "email": "contact@agency1.in",
                    "source": "OpenStreetMap; Overture Maps",
                    "contact_validation": "website format valid; +91 Indian phone format valid; public email format valid",
                    "lead_quality_score": 100,
                    "score_reason": "website available; valid Indian business phone; public business email; marketing relevance; geographic match",
                    "evidence": ["Homepage inspected"],
                }
            ],
            "csv_file": "data/bhubaneswar_digital_marketing_leads.csv",
        }

        req = ScrapeRequest(
            country="India",
            state="Odisha",
            city="Bhubaneswar",
            category="Digital Marketing",
            limit=10,
        )
        res = scrape(req)
        self.assertEqual(res["requested_city"], "Bhubaneswar")
        self.assertEqual(res["requested_category"], "Digital Marketing")
        self.assertEqual(res["discovered"], 10)
        self.assertEqual(res["qualified"], 2)
        self.assertEqual(len(res["leads"]), 1)
        self.assertEqual(res["leads"][0]["company_name"], "Creative Agency 1")

        # Validate with ScrapeResponse schema
        validated_resp = ScrapeResponse(**res)
        self.assertEqual(validated_resp.discovered, 10)

    def test_request_limit_above_200_allowed(self):
        # Verify no 200 artificial cap in request schema
        req = ScrapeRequest(
            country="India",
            state="Maharashtra",
            city="Mumbai",
            category="Digital Marketing",
            limit=500,  # Well beyond 200
        )
        self.assertEqual(req.limit, 500)

    def test_download_404(self):
        with self.assertRaises(HTTPException) as ctx:
            download_csv("data/non_existent_file.csv")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_download_success(self):
        # Create a small temp CSV
        test_file = Path("data/test_export.csv")
        test_file.write_text("col1,col2\nval1,val2\n", encoding="utf-8")
        try:
            resp = download_csv(str(test_file))
            self.assertIsInstance(resp, FileResponse)
            self.assertEqual(Path(resp.path).resolve(), test_file.resolve())
        finally:
            if test_file.exists():
                test_file.unlink()


if __name__ == "__main__":
    unittest.main()
