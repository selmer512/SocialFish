import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db
from core.simulation_service import (
    get_campaign_metrics,
    list_ai_provider_settings,
    list_campaigns,
    list_targets,
    record_simulation_event,
    update_ai_provider_settings,
)


class SimulationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "socialfish-test.db")
        migrate_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.campaign_id = self.conn.execute(
            "SELECT id FROM simulation_campaigns WHERE slug = ?",
            (SIMULATION_DEMO_SLUG,),
        ).fetchone()[0]

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_lists_campaigns_and_aggregate_metrics(self):
        campaigns = list_campaigns(self.conn)
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(campaigns[0]["slug"], SIMULATION_DEMO_SLUG)
        self.assertEqual(campaigns[0]["target_count"], 4)

        metrics = get_campaign_metrics(self.conn, self.campaign_id)
        self.assertEqual(metrics["aggregate"]["total_targets"], 4)
        self.assertEqual(metrics["aggregate"]["delivered"], 4)
        self.assertEqual(metrics["aggregate"]["opened"], 3)
        self.assertEqual(metrics["aggregate"]["link_clicked"], 2)
        self.assertEqual(metrics["aggregate"]["attachment_opened"], 1)
        self.assertEqual(set(metrics["channels"].keys()), {"email", "sms", "voice"})
        self.assertEqual(metrics["channels"]["email"]["total_targets"], 2)

    def test_lists_targets_with_boolean_rollup_fields(self):
        targets = list_targets(self.conn, self.campaign_id)
        self.assertEqual(len(targets), 4)
        self.assertIs(targets[0]["opened"], True)
        self.assertIs(targets[0]["forwarded"], False)

    def test_records_event_and_updates_target_rollup(self):
        voice_target_id = self.conn.execute(
            """
            SELECT id
            FROM simulation_targets
            WHERE campaign_id = ? AND channel = 'voice'
            """,
            (self.campaign_id,),
        ).fetchone()[0]

        event = record_simulation_event(
            self.conn,
            self.campaign_id,
            "link_click",
            target_id=voice_target_id,
            metadata={"lab": "phase-01"},
        )

        self.assertEqual(event["event_type"], "link_click")
        self.assertEqual(event["channel"], "voice")
        self.assertIn("phase-01", event["metadata"])

        target = self.conn.execute(
            """
            SELECT link_clicked, link_clicked_at
            FROM simulation_targets
            WHERE id = ?
            """,
            (voice_target_id,),
        ).fetchone()
        self.assertEqual(target[0], 1)
        self.assertIsNotNone(target[1])

    def test_rejects_unknown_event_types(self):
        with self.assertRaises(ValueError):
            record_simulation_event(self.conn, self.campaign_id, "unsupported")

    def test_lists_and_updates_ai_provider_settings_without_echoing_secret(self):
        providers = list_ai_provider_settings(self.conn)
        local_provider = next(provider for provider in providers if provider["provider_type"] == "local")
        self.assertNotIn("secret_placeholder", local_provider)
        self.assertFalse(local_provider["secret_configured"])

        updated = update_ai_provider_settings(
            self.conn,
            local_provider["id"],
            model_name="awareness-lab-v2",
            base_url="http://localhost:9999",
            enabled=False,
            secret="do-not-return-this",
        )

        self.assertEqual(updated["model_name"], "awareness-lab-v2")
        self.assertEqual(updated["base_url"], "http://localhost:9999")
        self.assertFalse(updated["enabled"])
        self.assertTrue(updated["secret_configured"])
        self.assertNotIn("secret_placeholder", updated)
        self.assertNotIn("do-not-return-this", str(updated))


if __name__ == "__main__":
    unittest.main()
