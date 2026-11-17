"""Unit tests for multi-locality campaign telemetry, smooth progress bar and ticker."""
import unittest
from unittest.mock import MagicMock, patch

from app.models import CampaignStatusResponse
from app.services.autonomous_worker import AutonomousScraperEngine
from app.services.orchestrator import execute_multi_locality_campaign


class TestCampaignTelemetry(unittest.TestCase):
    def test_campaign_status_response_schema(self):
        resp = CampaignStatusResponse(
            is_active=True,
            campaign_id="camp_test123",
            city="Mumbai",
            category="Digital Marketing",
            target_limit=100,
            current_shard="Andheri",
            shard_index=1,
            total_shards=8,
            leads_accumulated=12,
            percent_complete=15,
            active_message="Crawling Andheri [5/15]: brandhype.in",
            status="running",
            recent_activity=["Campaign started", "Crawling Andheri [5/15]: brandhype.in"],
        )
        self.assertEqual(resp.percent_complete, 15)
        self.assertEqual(resp.leads_accumulated, 12)
        self.assertIn("brandhype.in", resp.active_message)

    def test_orchestrator_sub_shard_step_callbacks(self):
        progress_events = []

        def mock_step_callback(event):
            progress_events.append(dict(event))

        # Mock execute_autonomous_run so it simulates incremental crawling and extraction
        def fake_autonomous_run(**kwargs):
            step_cb = kwargs.get("step_callback")
            if step_cb:
                step_cb({"stage": "queries", "query_count": 8})
                step_cb({"stage": "discovery", "discovered_count": 20})
                step_cb({"stage": "crawling", "crawled": 5, "total": 10, "domain": "example.com"})
                step_cb({"stage": "extraction", "company": "Example Media", "phone": "+919876543210", "verified_count": 1})
            return {
                "leads": [{"company_name": "Example Media", "phone": "+919876543210", "website": "https://example.com"}],
                "discovery_data": [{"url": "https://example.com", "domain": "example.com"}],
                "qualified": 1,
                "leads_with_phone": 1,
                "duration_seconds": 1.2,
            }

        with patch("app.services.orchestrator.execute_autonomous_run", side_effect=fake_autonomous_run):
            res = execute_multi_locality_campaign(
                city="Mumbai",
                category="Digital Marketing",
                target_limit=1,
                progress_callback=mock_step_callback,
            )

        self.assertGreater(len(progress_events), 4)
        # Verify percent_complete progressed incrementally above 0%
        percentages = [e["percent_complete"] for e in progress_events if "percent_complete" in e]
        self.assertTrue(any(p > 0 for p in percentages))
        self.assertEqual(percentages[-1], 100)

        # Verify active_messages were emitted
        messages = [e.get("active_message", "") for e in progress_events if e.get("active_message")]
        self.assertTrue(any("Starting sweep" in m or "Formulating" in m or "Discovered" in m or "Crawling" in m for m in messages))

    def test_autonomous_worker_status_propagation(self):
        engine = AutonomousScraperEngine()
        self.assertIn("active_message", engine._campaign_status)

        # Test worker on_progress handler updates active_message and percent_complete
        started = engine.start_campaign("Mumbai", "Digital Marketing", target_limit=20)
        self.assertTrue(started)

        status = engine.get_campaign_status()
        self.assertTrue(status["is_active"])
        self.assertGreaterEqual(status["percent_complete"], 1)
        self.assertIn("Mumbai", status["active_message"])

        engine.stop_campaign()


if __name__ == "__main__":
    unittest.main()
