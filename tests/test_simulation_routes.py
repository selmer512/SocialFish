import importlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db


class SimulationRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(sys, "argv", ["SocialFish.py", "route-user", "route-pass"]):
            cls.socialfish = importlib.import_module("SocialFish")
        cls.socialfish.app.config["TESTING"] = True

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "socialfish-routes.db")
        migrate_db(self.db_path)
        self.original_database = self.socialfish.DATABASE
        self.socialfish.DATABASE = self.db_path
        self.client = self.socialfish.app.test_client()
        self.client.post(
            "/neptune",
            data={"email": "route-user", "password": "route-pass"},
            follow_redirects=False,
        )

    def tearDown(self):
        self.socialfish.DATABASE = self.original_database
        self.temp_dir.cleanup()

    def _campaign_id(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT id FROM simulation_campaigns WHERE slug = ?",
                (SIMULATION_DEMO_SLUG,),
            ).fetchone()[0]
        finally:
            conn.close()

    def _target_id(self, channel):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                """
                SELECT id
                FROM simulation_targets
                WHERE campaign_id = ? AND channel = ?
                LIMIT 1
                """,
                (self._campaign_id(), channel),
            ).fetchone()[0]
        finally:
            conn.close()

    def test_authenticated_pages_render(self):
        simulations = self.client.get("/simulations")
        ai_settings = self.client.get("/ai-settings")

        self.assertEqual(simulations.status_code, 200)
        self.assertIn(b"Authorized internal training simulations only", simulations.data)
        self.assertIn(b"Simulation Center", simulations.data)
        self.assertIn(b"Channel Breakdown", simulations.data)
        self.assertIn(b"EMAIL", simulations.data)
        self.assertIn(b"SMS", simulations.data)
        self.assertIn(b"VOICE", simulations.data)
        self.assertIn(b"Target Activity", simulations.data)
        self.assertIn(b"Attachments opened", simulations.data)
        self.assertEqual(ai_settings.status_code, 200)
        self.assertIn(b"Secrets are accepted by the API but are never rendered back", ai_settings.data)
        self.assertIn(b"AI Provider Configuration", ai_settings.data)
        self.assertIn(b"Provider Type", ai_settings.data)
        self.assertIn(b"Model Name", ai_settings.data)
        self.assertIn(b"Base URL", ai_settings.data)
        self.assertIn(b"Secret placeholder", ai_settings.data)
        self.assertIn(b"Save Provider", ai_settings.data)

    def test_admin_dashboard_links_to_simulation_pages(self):
        response = self.client.get("/creds")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Simulation Center", response.data)
        self.assertIn(b"location.href='/simulations'", response.data)
        self.assertIn(b"AI Settings", response.data)
        self.assertIn(b"location.href='/ai-settings'", response.data)

    def test_metrics_api_returns_seeded_channel_data(self):
        response = self.client.get("/api/simulations/metrics")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["metrics"]["aggregate"]["total_targets"], 4)
        self.assertEqual(set(payload["metrics"]["channels"].keys()), {"email", "sms", "voice"})

    def test_events_api_records_allowed_lab_events(self):
        response = self.client.post(
            "/api/simulations/events",
            json={
                "campaign_id": self._campaign_id(),
                "target_id": self._target_id("voice"),
                "event_type": "attachment_open",
                "metadata": {"source": "route-test"},
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["event"]["event_type"], "attachment_open")
        self.assertNotIn("route-pass", str(payload))

    def test_ai_settings_api_does_not_echo_secret(self):
        conn = sqlite3.connect(self.db_path)
        try:
            provider_id = conn.execute(
                "SELECT id FROM ai_provider_configs WHERE provider_type = 'cloud'"
            ).fetchone()[0]
        finally:
            conn.close()

        response = self.client.post(
            "/api/ai-settings",
            json={
                "provider_id": provider_id,
                "model_name": "cloud-awareness-model-v2",
                "base_url": "https://api.example.test/v2",
                "enabled": True,
                "secret": "super-secret-route-test",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["provider"]["secret_configured"])
        self.assertNotIn("secret_placeholder", payload["provider"])
        self.assertNotIn("super-secret-route-test", str(payload))


if __name__ == "__main__":
    unittest.main()
