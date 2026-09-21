import importlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.db_migration import migrate_db


class SimulationPrototypeSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(sys, "argv", ["SocialFish.py", "smoke-user", "smoke-pass"]):
            cls.socialfish = importlib.import_module("SocialFish")
        cls.socialfish.app.config["TESTING"] = True
        cls.socialfish.users["smoke-user"] = {"password": "smoke-pass"}

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "socialfish-smoke.db")
        migrate_db(self.db_path)
        self.original_database = self.socialfish.DATABASE
        self.socialfish.DATABASE = self.db_path
        self.client = self.socialfish.app.test_client()

    def tearDown(self):
        self.socialfish.DATABASE = self.original_database
        self.temp_dir.cleanup()

    def _login(self):
        response = self.client.post(
            "/neptune",
            data={"email": "smoke-user", "password": "smoke-pass"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def _cloud_provider_id(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT id FROM ai_provider_configs WHERE provider_type = 'cloud'"
            ).fetchone()[0]
        finally:
            conn.close()

    def test_authenticated_prototype_routes_metrics_and_secret_redaction(self):
        self._login()

        simulations = self.client.get("/simulations")
        ai_settings = self.client.get("/ai-settings")
        metrics = self.client.get("/api/simulations/metrics")

        self.assertEqual(simulations.status_code, 200)
        self.assertIn(b"Simulation Center", simulations.data)
        self.assertEqual(ai_settings.status_code, 200)
        self.assertIn(b"AI Provider Configuration", ai_settings.data)

        self.assertEqual(metrics.status_code, 200)
        metrics_payload = metrics.get_json()
        self.assertEqual(metrics_payload["status"], "ok")
        channels = metrics_payload["metrics"]["channels"]
        self.assertEqual(set(channels.keys()), {"email", "sms", "voice"})
        self.assertEqual(channels["email"]["total_targets"], 2)
        self.assertEqual(channels["sms"]["total_targets"], 1)
        self.assertEqual(channels["voice"]["total_targets"], 1)

        secret_value = "smoke-test-secret-never-echo"
        ai_response = self.client.post(
            "/api/ai-settings",
            json={
                "provider_id": self._cloud_provider_id(),
                "model_name": "cloud-awareness-smoke-model",
                "base_url": "https://api.example.test/smoke",
                "enabled": True,
                "secret": secret_value,
            },
        )
        ai_payload = ai_response.get_json()

        self.assertEqual(ai_response.status_code, 200)
        self.assertEqual(ai_payload["status"], "ok")
        self.assertTrue(ai_payload["provider"]["secret_configured"])
        self.assertNotIn("secret_placeholder", ai_payload["provider"])
        self.assertNotIn(secret_value, str(ai_payload))


if __name__ == "__main__":
    unittest.main()
