"""Unit tests for the autonomous self-scraping background worker and daemon."""
import unittest

from app.services.autonomous_worker import AutonomousScraperEngine


class TestAutonomousWorker(unittest.TestCase):
    def setUp(self):
        self.engine = AutonomousScraperEngine()

    def tearDown(self):
        if self.engine.is_active():
            self.engine.stop()

    def test_initial_state(self):
        status = self.engine.get_status()
        self.assertFalse(status["is_running"])
        self.assertEqual(status["total_runs_completed"], 0)
        self.assertGreater(status["targets_count"], 0)

    def test_start_and_stop(self):
        started = self.engine.start(interval_seconds=60, default_limit=5)
        self.assertTrue(started)
        self.assertTrue(self.engine.is_active())

        # Calling start again while active should return False
        self.assertFalse(self.engine.start())

        stopped = self.engine.stop()
        self.assertTrue(stopped)
        self.assertFalse(self.engine.is_active())

    def test_run_sweep(self):
        sweep = self.engine.run_sweep(
            targets=[{"city": "Bhubaneswar", "category": "Digital Marketing"}],
            limit_per_target=5,
            phone_required=True,
        )
        self.assertEqual(sweep["status"], "completed")
        self.assertEqual(sweep["targets_scraped"], 1)
        self.assertGreater(sweep["total_qualified"], 0)
        self.assertGreater(sweep["total_with_phone"], 0)


if __name__ == "__main__":
    unittest.main()

