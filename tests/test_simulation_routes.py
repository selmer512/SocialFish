import importlib
import io
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
        campaigns = self.client.get("/simulations/campaigns")
        new_campaign = self.client.get("/simulations/campaigns/new")
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
        self.assertEqual(campaigns.status_code, 200)
        self.assertIn(b"Campaign Management", campaigns.data)
        self.assertIn(b"New Campaign", campaigns.data)
        self.assertIn(b"Delivered", campaigns.data)
        self.assertEqual(new_campaign.status_code, 200)
        self.assertIn(b"Create Campaign", new_campaign.data)
        self.assertIn(b'name="selected_channels"', new_campaign.data)
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

    def test_campaign_management_routes_create_update_detail_and_archive(self):
        create_response = self.client.post(
            "/simulations/campaigns",
            data={
                "name": "Route Managed Campaign",
                "description": "Created through the authenticated route",
                "objective": "Measure reporting behavior",
                "training_owner": "Security Awareness",
                "status": "draft",
                "selected_channels": ["email", "sms"],
                "landing_url": "https://training.example.test/landing",
                "training_url": "https://training.example.test/course",
                "start_date": "2026-10-01",
                "end_date": "2026-10-31",
                "authorized_scope": "Internal route test users only",
            },
            follow_redirects=False,
        )

        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/simulations/campaigns/", create_response.headers["Location"])

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, name, status, selected_channels
                FROM simulation_campaigns
                WHERE slug = 'route-managed-campaign'
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        campaign_id = row[0]
        self.assertEqual(row[1], "Route Managed Campaign")
        self.assertEqual(row[2], "draft")
        self.assertIn("sms", row[3])

        detail_response = self.client.get("/simulations/campaigns/{}".format(campaign_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b"Edit Campaign", detail_response.data)
        self.assertIn(b"Add Targets", detail_response.data)
        self.assertIn(b"Manual Target Entry", detail_response.data)
        self.assertIn(b"CSV Upload", detail_response.data)
        self.assertIn(b"Expected columns", detail_response.data)
        self.assertIn(b'name="targets_csv"', detail_response.data)
        self.assertIn(b"Targets", detail_response.data)
        self.assertIn(b"Events", detail_response.data)
        self.assertIn(b"Archive", detail_response.data)

        update_response = self.client.post(
            "/simulations/campaigns/{}".format(campaign_id),
            data={
                "name": "Route Managed Campaign FY26",
                "description": "Updated through the authenticated route",
                "objective": "Reduce unsafe clicks",
                "training_owner": "Cybersecurity Team",
                "status": "active",
                "selected_channels": ["voice", "email"],
                "landing_url": "https://training.example.test/landing-v2",
                "training_url": "https://training.example.test/course-v2",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
                "authorized_scope": "Updated internal route test users only",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        conn = sqlite3.connect(self.db_path)
        try:
            updated = conn.execute(
                """
                SELECT slug, status, training_owner, selected_channels
                FROM simulation_campaigns
                WHERE id = ?
                """,
                (campaign_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(updated[0], "route-managed-campaign-fy26")
        self.assertEqual(updated[1], "active")
        self.assertEqual(updated[2], "Cybersecurity Team")
        self.assertIn("voice", updated[3])

        archive_response = self.client.post(
            "/simulations/campaigns/{}/archive".format(campaign_id),
            follow_redirects=True,
        )
        self.assertEqual(archive_response.status_code, 200)
        self.assertIn(b"Campaign archived. Historical metrics were preserved.", archive_response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            archived = conn.execute(
                "SELECT status, archived_at FROM simulation_campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(archived[0], "archived")
        self.assertIsNotNone(archived[1])

    def test_campaign_create_route_displays_validation_errors(self):
        response = self.client.post(
            "/simulations/campaigns",
            data={"name": "", "selected_channels": ["email"]},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Campaign name is required.", response.data)

    def test_target_management_routes_create_update_and_archive(self):
        campaign_id = self._campaign_id()

        create_response = self.client.post(
            "/simulations/campaigns/{}/targets".format(campaign_id),
            data={
                "name": "Route Target",
                "display_name": "Route Target Display",
                "email": "ROUTE.TARGET@EXAMPLE.TEST",
                "department": "Security",
                "manager": "Route Manager",
                "channel": "email",
                "active": "on",
            },
            follow_redirects=True,
        )

        self.assertEqual(create_response.status_code, 200)
        self.assertIn(b"Target Route Target Display added to the campaign.", create_response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            target = conn.execute(
                """
                SELECT id, email, display_name, department, manager, active
                FROM simulation_targets
                WHERE name = 'Route Target'
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(target)
        target_id = target[0]
        self.assertEqual(target[1], "route.target@example.test")
        self.assertEqual(target[2], "Route Target Display")
        self.assertEqual(target[5], 1)

        update_response = self.client.post(
            "/simulations/targets/{}".format(target_id),
            data={
                "name": "Route Target Updated",
                "display_name": "Route Target Updated",
                "email": "route.updated@example.test",
                "phone": "",
                "department": "Awareness",
                "manager": "Updated Manager",
                "source": "manual",
                "channel": "email",
                "active": "true",
            },
            follow_redirects=True,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertIn(b"Target Route Target Updated updated.", update_response.data)
        self.assertIn(b'name="source" value="manual"', update_response.data)
        self.assertIn(b"Route Target Updated", update_response.data)

        archive_response = self.client.post(
            "/simulations/targets/{}/archive".format(target_id),
            follow_redirects=True,
        )
        self.assertEqual(archive_response.status_code, 200)
        self.assertIn(b"Target archived. Historical events were preserved.", archive_response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            archived = conn.execute(
                "SELECT name, active, archived_at FROM simulation_targets WHERE id = ?",
                (target_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(archived[0], "Route Target Updated")
        self.assertEqual(archived[1], 0)
        self.assertIsNotNone(archived[2])

    def test_target_create_route_displays_validation_errors(self):
        response = self.client.post(
            "/simulations/campaigns/{}/targets".format(self._campaign_id()),
            data={"name": "No Email", "channel": "email"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Target requires at least one contact method", response.data)

    def test_target_csv_upload_records_batch_and_flashes_row_errors(self):
        campaign_id = self._campaign_id()
        csv_content = (
            "name,email,phone,channel,department\n"
            "CSV Route One,csv.one@example.test,,email,Security\n"
            "CSV Route Bad,,555-1212,email,Awareness\n"
            "CSV Route Two,,+15551234567,sms,Operations\n"
        )

        response = self.client.post(
            "/simulations/campaigns/{}/targets/upload".format(campaign_id),
            data={
                "targets_csv": (
                    io.BytesIO(csv_content.encode("utf-8")),
                    "route-targets.csv",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Imported 2 target(s) with 1 validation error(s).", response.data)
        self.assertIn(b"CSV row 3: Email channel targets require an email address.", response.data)
        self.assertIn(b"Import Validation Feedback", response.data)
        self.assertIn(b"route-targets.csv", response.data)
        self.assertIn(b"Row 3: Email channel targets require an email address.", response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            batch = conn.execute(
                """
                SELECT original_filename, total_rows, valid_rows, invalid_rows, imported_rows
                FROM simulation_import_batches
                WHERE campaign_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
            imported = conn.execute(
                """
                SELECT COUNT(*)
                FROM simulation_targets
                WHERE campaign_id = ? AND source = 'csv'
                """,
                (campaign_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(batch, ("route-targets.csv", 3, 2, 1, 2))
        self.assertEqual(imported, 2)


if __name__ == "__main__":
    unittest.main()
