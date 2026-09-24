import importlib
import hashlib
import hmac
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db
from core.simulation_service import create_campaign, create_target, record_simulation_event


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

    def _provider_id(self, provider_type="local"):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT id FROM ai_provider_configs WHERE provider_type = ?",
                (provider_type,),
            ).fetchone()[0]
        finally:
            conn.close()

    def _delivery_provider_id(self, provider_key):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT id FROM simulation_channel_providers WHERE provider_key = ?",
                (provider_key,),
            ).fetchone()[0]
        finally:
            conn.close()

    def _administrative_audit_events(self, campaign_id=None):
        conn = sqlite3.connect(self.db_path)
        try:
            params = []
            where = ""
            if campaign_id is not None:
                where = "WHERE campaign_id = ?"
                params.append(campaign_id)
            rows = conn.execute(
                """
                SELECT action_type, entity_type, entity_id, campaign_id, channel, metadata_json
                FROM administrative_audit_events
                {}
                ORDER BY id ASC
                """.format(where),
                params,
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "action_type": row[0],
                "entity_type": row[1],
                "entity_id": row[2],
                "campaign_id": row[3],
                "channel": row[4],
                "metadata": json.loads(row[5] or "{}"),
            }
            for row in rows
        ]

    def test_authenticated_pages_render(self):
        simulations = self.client.get("/simulations")
        metrics_dashboard = self.client.get("/simulations/metrics")
        campaigns = self.client.get("/simulations/campaigns")
        new_campaign = self.client.get("/simulations/campaigns/new")
        ai_settings = self.client.get("/ai-settings")
        ai_builder = self.client.get("/simulations/ai-builder")
        audit_log = self.client.get("/audit-log")

        self.assertEqual(simulations.status_code, 200)
        self.assertIn(b"Authorized internal training simulations only", simulations.data)
        self.assertIn(b"Simulation Center", simulations.data)
        self.assertIn(b"/simulations/metrics", simulations.data)
        self.assertIn(b"Channel Breakdown", simulations.data)
        self.assertIn(b"EMAIL", simulations.data)
        self.assertIn(b"SMS", simulations.data)
        self.assertIn(b"VOICE", simulations.data)
        self.assertIn(b"Target Activity", simulations.data)
        self.assertIn(b"Attachments opened", simulations.data)
        self.assertEqual(metrics_dashboard.status_code, 200)
        self.assertIn(b"Simulation Metrics", metrics_dashboard.data)
        self.assertIn(b"Portfolio Summary", metrics_dashboard.data)
        self.assertIn(b"Channel Comparison", metrics_dashboard.data)
        self.assertIn(b"Campaign Trends", metrics_dashboard.data)
        self.assertIn(b"Target Risk Summary", metrics_dashboard.data)
        self.assertIn(b'name="campaign_id"', metrics_dashboard.data)
        self.assertIn(b'name="channel"', metrics_dashboard.data)
        self.assertIn(b'name="department"', metrics_dashboard.data)
        self.assertIn(b'name="delivery_status"', metrics_dashboard.data)
        self.assertEqual(campaigns.status_code, 200)
        self.assertIn(b"Campaign Management", campaigns.data)
        self.assertIn(b"New Campaign", campaigns.data)
        self.assertIn(b"Delivered", campaigns.data)
        self.assertEqual(new_campaign.status_code, 200)
        self.assertIn(b"Create Campaign", new_campaign.data)
        self.assertIn(b'name="selected_channels"', new_campaign.data)
        self.assertIn(b'name="authorization_statement"', new_campaign.data)
        self.assertEqual(ai_settings.status_code, 200)
        self.assertIn(b"Secrets are accepted by the API but are never rendered back", ai_settings.data)
        self.assertIn(b"AI Provider Configuration", ai_settings.data)
        self.assertIn(b"Provider Type", ai_settings.data)
        self.assertIn(b"Model Name", ai_settings.data)
        self.assertIn(b"Base URL", ai_settings.data)
        self.assertIn(b"Secret placeholder", ai_settings.data)
        self.assertIn(b"Save Provider", ai_settings.data)
        self.assertIn(b"Delivery Provider Configuration", ai_settings.data)
        self.assertIn(b"Dry-run Email", ai_settings.data)
        self.assertIn(b"Save Delivery Provider", ai_settings.data)
        self.assertIn(b"/api/delivery-settings", ai_settings.data)
        self.assertEqual(ai_builder.status_code, 200)
        self.assertIn(b"AI Scenario Builder", ai_builder.data)
        self.assertIn(b"Authorized internal training simulations only", ai_builder.data)
        self.assertIn(b"/api/simulations/ai/generate", ai_builder.data)
        self.assertIn(b"Draft Review", ai_builder.data)
        self.assertIn(b"Save Selected Drafts", ai_builder.data)
        self.assertIn(b"Risk Flags", ai_builder.data)
        self.assertIn(b"Safety Notes", ai_builder.data)
        self.assertIn(b'data-preview-pane="email"', ai_builder.data)
        self.assertIn(b'data-preview-pane="sms"', ai_builder.data)
        self.assertIn(b'data-preview-pane="voice"', ai_builder.data)
        self.assertIn(b"/api/simulations/ai/save-draft", ai_builder.data)
        self.assertEqual(audit_log.status_code, 200)
        self.assertIn(b"Audit Log", audit_log.data)
        self.assertIn(b'name="action_type"', audit_log.data)
        self.assertIn(b'name="entity_type"', audit_log.data)
        self.assertIn(b'name="channel"', audit_log.data)
        self.assertIn(b'name="actor"', audit_log.data)
        self.assertIn(b'name="campaign_id"', audit_log.data)
        self.assertIn(b'name="start_date"', audit_log.data)
        self.assertIn(b'name="end_date"', audit_log.data)

    def test_audit_log_requires_login(self):
        anonymous_client = self.socialfish.app.test_client()

        response = anonymous_client.get("/audit-log")
        detail_response = anonymous_client.get("/audit-log/1")

        self.assertIn(response.status_code, (200, 401, 302))
        self.assertIn(b"Unauthorized", response.data)
        self.assertNotIn(b"Audit Log", response.data)
        self.assertIn(detail_response.status_code, (200, 401, 302))
        self.assertIn(b"Unauthorized", detail_response.data)
        self.assertNotIn(b"Audit Event Detail", detail_response.data)

    def test_audit_log_filters_and_detail_view_render_redacted_metadata(self):
        campaign_id = self._campaign_id()
        provider_id = self._provider_id("local")

        self.client.post(
            "/api/ai-settings",
            json={
                "provider_id": provider_id,
                "name": "Route Local Provider",
                "provider_type": "local",
                "model_name": "route-model",
                "base_url": "http://localhost.test",
                "enabled": True,
                "secret": "plaintext-route-secret",
                "description": "Route test provider",
            },
        )
        self.client.post(
            "/simulations/campaigns/{}/deliveries/preview".format(campaign_id),
            json={"mode": "dry_run"},
        )

        log_response = self.client.get(
            "/audit-log?action_type=ai_provider.configure&entity_type=ai_provider&actor=route-user"
        )
        self.assertEqual(log_response.status_code, 200)
        self.assertIn(b"ai_provider.configure", log_response.data)
        self.assertIn(b"Route Local Provider", log_response.data)
        self.assertIn(b"[redacted]", log_response.data)
        self.assertNotIn(b"plaintext-route-secret", log_response.data)
        self.assertEqual(log_response.data.count(b'<span class="badge badge-info">delivery.preview'), 0)

        campaign_log_response = self.client.get("/audit-log?campaign_id={}".format(campaign_id))
        self.assertEqual(campaign_log_response.status_code, 200)
        self.assertIn(b"delivery.preview", campaign_log_response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            audit_id = conn.execute(
                """
                SELECT id
                FROM administrative_audit_events
                WHERE action_type = 'ai_provider.configure'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()[0]
        finally:
            conn.close()

        detail_response = self.client.get("/audit-log/{}".format(audit_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b"Audit Event Detail", detail_response.data)
        self.assertIn(b"ai_provider.configure", detail_response.data)
        self.assertIn(b"[redacted]", detail_response.data)
        self.assertNotIn(b"plaintext-route-secret", detail_response.data)

    def test_ai_generation_api_generates_and_saves_campaign_draft(self):
        campaign_id = self._campaign_id()
        provider_id = self._provider_id("local")

        generate_response = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "scenario_goal": "Practice reporting suspicious invoice requests",
                "audience": "Finance team",
                "channels": ["email", "sms", "voice"],
                "tone": "calm",
                "difficulty": "introductory",
                "training_reminder": "Use the report button before taking action.",
            },
        )
        payload = generate_response.get_json()

        self.assertEqual(generate_response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["generation"]["provider"]["id"], provider_id)
        self.assertEqual(set(payload["generation"]["channels"]), {"email", "sms", "voice"})
        self.assertIn("Training simulation", payload["generation"]["draft"]["email_subject"])
        self.assertIn("authorized_security_awareness_training", str(payload))
        self.assertNotIn("secret_placeholder", str(payload))

        save_response = self.client.post(
            "/api/simulations/ai/save-draft",
            json={
                "campaign_id": campaign_id,
                "provider": payload["generation"]["provider"],
                "channels": payload["generation"]["channels"],
                "draft": payload["generation"]["draft"],
                "risk_flags": payload["generation"]["risk_flags"],
                "safety_notes": payload["generation"]["safety_notes"],
                "metadata": payload["generation"]["metadata"],
            },
        )
        saved = save_response.get_json()

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["draft"]["campaign_id"], campaign_id)
        self.assertEqual(set(saved["draft"]["channels"]), {"email", "sms", "voice"})
        self.assertIn("authorized_training_label_present", saved["draft"]["risk_flags"])

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT campaign_id, provider_id, email_subject, sms_body, voice_script
                FROM ai_campaign_drafts
                WHERE id = ?
                """,
                (saved["draft"]["id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], campaign_id)
        self.assertEqual(row[1], provider_id)
        self.assertIn("Practice reporting suspicious invoice requests", row[2])
        self.assertIn("Authorized training simulation", row[3])
        self.assertIn("authorized security awareness training simulation", row[4].lower())

        second_save_response = self.client.post(
            "/api/simulations/ai/save-draft",
            json={
                "campaign_id": campaign_id,
                "provider": payload["generation"]["provider"],
                "channels": ["sms"],
                "draft": {
                    "sms_body": "Authorized training simulation SMS follow-up.",
                    "training_text": "Report suspicious invoice requests through approved channels.",
                },
                "risk_flags": ["authorized_training_label_present"],
                "safety_notes": ["Saved as a second channel-specific draft version."],
                "metadata": payload["generation"]["metadata"],
            },
        )
        self.assertEqual(second_save_response.status_code, 200)

        detail_response = self.client.get("/simulations/campaigns/{}".format(campaign_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b"AI Draft History", detail_response.data)
        self.assertIn(b"Channel-Specific Content", detail_response.data)
        self.assertIn(b"Version #", detail_response.data)
        self.assertIn(b"Practice reporting suspicious invoice requests", detail_response.data)
        self.assertIn(b"Authorized training simulation SMS follow-up.", detail_response.data)
        self.assertIn(b"/simulations/ai-builder?campaign_id=", detail_response.data)
        self.assertIn(b"/ai-settings", detail_response.data)

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign_id)]
        self.assertIn("generation.create", audit_actions)
        self.assertEqual(audit_actions.count("generation.draft_save"), 2)

    def test_ai_generation_api_covers_channels_and_redacts_secrets(self):
        campaign_id = self._campaign_id()
        provider_id = self._provider_id("local")
        secret = "route-secret-never-returned"

        settings_response = self.client.post(
            "/api/ai-settings",
            json={
                "provider_id": provider_id,
                "model_name": "local-simulation-model",
                "enabled": True,
                "secret": secret,
            },
        )
        settings_payload = settings_response.get_json()
        self.assertEqual(settings_response.status_code, 200)
        self.assertTrue(settings_payload["provider"]["secret_configured"])
        self.assertNotIn(secret, str(settings_payload))
        self.assertNotIn("secret_placeholder", str(settings_payload))

        settings_page = self.client.get("/ai-settings")
        self.assertEqual(settings_page.status_code, 200)
        self.assertNotIn(secret.encode("utf-8"), settings_page.data)

        generate_response = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "scenario_goal": "Practice verifying unexpected vendor changes",
                "audience": "Accounts payable team",
                "channels": ["email", "sms", "voice"],
                "tone": "plainspoken",
                "difficulty": "standard",
                "training_reminder": "Contact the vendor owner through the approved directory.",
            },
        )
        payload = generate_response.get_json()

        self.assertEqual(generate_response.status_code, 200)
        self.assertEqual(set(payload["generation"]["channels"]), {"email", "sms", "voice"})
        self.assertIn("Training simulation", payload["generation"]["draft"]["email_subject"])
        self.assertIn("authorized security awareness training simulation", payload["generation"]["draft"]["email_body"].lower())
        self.assertIn("Authorized training simulation", payload["generation"]["draft"]["sms_body"])
        self.assertIn("authorized security awareness training simulation", payload["generation"]["draft"]["voice_script"].lower())
        self.assertIn("credential_collection_disallowed", payload["generation"]["risk_flags"])
        self.assertNotIn(secret, str(payload))
        self.assertNotIn("secret_placeholder", str(payload))

        audit_events = self._administrative_audit_events()
        provider_events = [event for event in audit_events if event["action_type"] == "ai_provider.configure"]
        self.assertEqual(len(provider_events), 1)
        self.assertEqual(provider_events[0]["entity_type"], "ai_provider")
        self.assertEqual(provider_events[0]["metadata"]["request"]["secret"], "[redacted]")

    def test_ai_generation_api_returns_structured_errors(self):
        missing_provider = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "scenario_goal": "Practice safe reporting",
                "audience": "Operations",
                "channels": ["email"],
            },
        )
        missing_payload = missing_provider.get_json()
        self.assertEqual(missing_provider.status_code, 400)
        self.assertEqual(missing_payload["error"]["type"], "missing_provider_configuration")

        blocked = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "provider_id": self._provider_id("local"),
                "scenario_goal": "Capture user credentials during the exercise",
                "audience": "Finance",
                "channels": ["email"],
            },
        )
        blocked_payload = blocked.get_json()
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked_payload["error"]["type"], "blocked_content")
        self.assertIn("credential_harvesting_request", blocked_payload["error"]["risk_flags"])

        disabled = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "provider_id": self._provider_id("cloud"),
                "scenario_goal": "Practice safe reporting",
                "audience": "Operations",
                "channels": ["email"],
            },
        )
        disabled_payload = disabled.get_json()
        self.assertEqual(disabled.status_code, 400)
        self.assertEqual(disabled_payload["error"]["type"], "missing_provider_configuration")

    def test_admin_dashboard_links_to_simulation_pages(self):
        response = self.client.get("/creds")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Simulation Center", response.data)
        self.assertIn(b"location.href='/simulations'", response.data)
        self.assertIn(b"Directory Integrations", response.data)
        self.assertIn(b"location.href='/integrations/directory'", response.data)
        self.assertIn(b"AI Settings", response.data)
        self.assertIn(b"location.href='/ai-settings'", response.data)

    def test_metrics_api_returns_seeded_channel_data(self):
        response = self.client.get("/api/simulations/metrics")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["metrics"]["aggregate"]["total_targets"], 4)
        self.assertEqual(set(payload["metrics"]["channels"].keys()), {"email", "sms", "voice"})

    def test_reporting_metrics_apis_return_filtered_campaign_target_and_overview_data(self):
        conn = sqlite3.connect(self.db_path)
        try:
            active_campaign = create_campaign(
                conn,
                "Route Metrics Active",
                status="active",
                selected_channels=["email", "sms"],
            )
            paused_campaign = create_campaign(
                conn,
                "Route Metrics Paused",
                status="paused",
                selected_channels=["email"],
            )
            email_target = create_target(
                conn,
                active_campaign["id"],
                name="Route Metrics Email",
                email="metrics.email@example.test",
                department="Finance",
                channel="email",
            )
            sms_target = create_target(
                conn,
                active_campaign["id"],
                name="Route Metrics SMS",
                phone="+15550102222",
                department="Operations",
                channel="sms",
            )
            paused_target = create_target(
                conn,
                paused_campaign["id"],
                name="Route Metrics Paused",
                email="metrics.paused@example.test",
                department="Finance",
                channel="email",
            )
            record_simulation_event(
                conn,
                active_campaign["id"],
                "delivered",
                target_id=email_target["id"],
                channel="email",
                occurred_at="2026-09-20T10:00:00+00:00",
            )
            record_simulation_event(
                conn,
                active_campaign["id"],
                "open",
                target_id=email_target["id"],
                channel="email",
                occurred_at="2026-09-20T11:00:00+00:00",
            )
            record_simulation_event(
                conn,
                active_campaign["id"],
                "delivered",
                target_id=sms_target["id"],
                channel="sms",
                occurred_at="2026-09-21T10:00:00+00:00",
            )
            record_simulation_event(
                conn,
                paused_campaign["id"],
                "delivered",
                target_id=paused_target["id"],
                channel="email",
                occurred_at="2026-09-20T10:00:00+00:00",
            )
        finally:
            conn.close()

        campaign_response = self.client.get(
            "/api/simulations/campaigns/{}/metrics?channel=email&start_date=2026-09-20&end_date=2026-09-20".format(
                active_campaign["id"]
            )
        )
        campaign_payload = campaign_response.get_json()

        self.assertEqual(campaign_response.status_code, 200)
        self.assertEqual(campaign_payload["status"], "ok")
        self.assertEqual(campaign_payload["campaign_id"], active_campaign["id"])
        self.assertEqual(campaign_payload["metrics"]["aggregate"]["total_targets"], 1)
        self.assertEqual(campaign_payload["metrics"]["aggregate"]["delivered"], 1)
        self.assertEqual(campaign_payload["metrics"]["aggregate"]["opened"], 1)
        self.assertEqual(campaign_payload["metrics"]["filters"]["channels"], ["email"])

        targets_response = self.client.get(
            "/api/simulations/campaigns/{}/targets/metrics?department=Operations".format(
                active_campaign["id"]
            )
        )
        targets_payload = targets_response.get_json()

        self.assertEqual(targets_response.status_code, 200)
        self.assertEqual(len(targets_payload["targets"]), 1)
        self.assertEqual(targets_payload["targets"][0]["target_id"], sms_target["id"])
        self.assertEqual(targets_payload["targets"][0]["department"], "Operations")

        overview_response = self.client.get(
            "/api/simulations/metrics/overview?channel=email&start_date=2026-09-20&end_date=2026-09-20"
        )
        overview_payload = overview_response.get_json()

        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(overview_payload["status"], "ok")
        self.assertEqual(overview_payload["metrics"]["aggregate"]["delivered"], 1)
        self.assertEqual(overview_payload["metrics"]["filters"]["active_campaigns_only"], True)

    def test_metrics_apis_reject_unknown_channel_filter(self):
        response = self.client.get("/api/simulations/metrics/overview?channel=fax")
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["type"], "simulation_metrics_overview_error")
        self.assertIn("channel must be one of", payload["error"]["message"].lower())

    def test_metrics_apis_reject_invalid_dates_and_delivery_statuses(self):
        bad_date_response = self.client.get("/api/simulations/metrics/overview?start_date=09/22/2026")
        bad_range_response = self.client.get(
            "/api/simulations/metrics/overview?start_date=2026-09-23&end_date=2026-09-22"
        )
        bad_status_response = self.client.get("/api/simulations/metrics/overview?delivery_status=opened")

        self.assertEqual(bad_date_response.status_code, 400)
        self.assertEqual(bad_date_response.get_json()["error"]["type"], "simulation_metrics_overview_error")
        self.assertIn("YYYY-MM-DD", bad_date_response.get_json()["error"]["message"])
        self.assertEqual(bad_range_response.status_code, 400)
        self.assertIn("Start date", bad_range_response.get_json()["error"]["message"])
        self.assertEqual(bad_status_response.status_code, 400)
        self.assertIn("Delivery status must be one of", bad_status_response.get_json()["error"]["message"])

    def test_metrics_dashboard_renders_filtered_campaign_reporting(self):
        conn = sqlite3.connect(self.db_path)
        try:
            campaign = create_campaign(
                conn,
                "Dashboard Metrics Campaign",
                status="active",
                selected_channels=["email", "voice"],
            )
            email_target = create_target(
                conn,
                campaign["id"],
                name="Dashboard Metrics Email",
                email="dashboard.metrics@example.test",
                department="Finance",
                channel="email",
            )
            voice_target = create_target(
                conn,
                campaign["id"],
                name="Dashboard Metrics Voice",
                phone="+15550103333",
                department="Operations",
                channel="voice",
            )
            record_simulation_event(
                conn,
                campaign["id"],
                "delivered",
                target_id=email_target["id"],
                channel="email",
                occurred_at="2026-09-22T10:00:00+00:00",
            )
            record_simulation_event(
                conn,
                campaign["id"],
                "link_click",
                target_id=email_target["id"],
                channel="email",
                occurred_at="2026-09-22T10:10:00+00:00",
            )
            record_simulation_event(
                conn,
                campaign["id"],
                "voice_response",
                target_id=voice_target["id"],
                channel="voice",
                occurred_at="2026-09-22T10:15:00+00:00",
            )
        finally:
            conn.close()

        response = self.client.get(
            "/simulations/metrics?campaign_id={}&channel=email&department=Finance&delivery_status=delivered&start_date=2026-09-22&end_date=2026-09-22".format(
                campaign["id"]
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard Metrics Campaign", response.data)
        self.assertIn(b"Dashboard Metrics Email", response.data)
        self.assertNotIn(b"Dashboard Metrics Voice</", response.data)
        self.assertIn(b"selected>EMAIL</option>", response.data)
        self.assertIn(b"selected>Finance</option>", response.data)
        self.assertIn(b"value=\"2026-09-22\"", response.data)
        self.assertIn(b"Risk", response.data)

    def test_campaign_reporting_exports_csv_json_and_printable_report(self):
        conn = sqlite3.connect(self.db_path)
        try:
            campaign = create_campaign(
                conn,
                "Export Metrics Campaign",
                status="active",
                selected_channels=["email"],
            )
            target = create_target(
                conn,
                campaign["id"],
                name="Export Metrics Target",
                email="export.metrics@example.test",
                department="Finance",
                channel="email",
            )
            record_simulation_event(
                conn,
                campaign["id"],
                "delivered",
                target_id=target["id"],
                channel="email",
                provider="smtp_email",
                provider_event_id="evt-export-route",
                metadata={
                    "source": "provider-webhook",
                    "webhook_secret": "route-export-secret",
                    "nested": {"api_key": "route-export-api-key"},
                },
            )
            record_simulation_event(
                conn,
                campaign["id"],
                "link_click",
                target_id=target["id"],
                channel="email",
                metadata={"source": "tracking-token"},
            )
        finally:
            conn.close()

        csv_response = self.client.get(
            "/simulations/campaigns/{}/targets/metrics.csv?department=Finance".format(campaign["id"])
        )
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response.mimetype, "text/csv")
        self.assertIn(
            "attachment; filename=simulation-campaign-{}-target-metrics.csv".format(campaign["id"]),
            csv_response.headers["Content-Disposition"],
        )
        self.assertIn(b"target_id", csv_response.data)
        self.assertIn(b"display_name", csv_response.data)
        self.assertIn(b"Export Metrics Target", csv_response.data)
        self.assertIn(b"link_clicked", csv_response.data)

        json_response = self.client.get("/simulations/campaigns/{}/events.json".format(campaign["id"]))
        payload = json.loads(json_response.data.decode("utf-8"))
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.mimetype, "application/json")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["campaign"]["name"], "Export Metrics Campaign")
        self.assertEqual(len(payload["events"]), 2)
        self.assertNotIn("route-export-secret", json_response.data.decode("utf-8"))
        self.assertNotIn("route-export-api-key", json_response.data.decode("utf-8"))
        self.assertIn("[REDACTED]", json_response.data.decode("utf-8"))

        report_response = self.client.get("/simulations/campaigns/{}/report?department=Finance".format(campaign["id"]))
        self.assertEqual(report_response.status_code, 200)
        self.assertIn(b"Simulation campaign report", report_response.data)
        self.assertIn(b"Export Metrics Campaign", report_response.data)
        self.assertIn(b"Target Metrics", report_response.data)
        self.assertIn(b"Event Sources", report_response.data)

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign["id"])]
        self.assertIn("export.metrics", audit_actions)
        self.assertIn("export.events", audit_actions)
        self.assertIn("report.view", audit_actions)

    def test_campaign_reporting_views_render_empty_campaign_state(self):
        conn = sqlite3.connect(self.db_path)
        try:
            campaign = create_campaign(
                conn,
                "Empty Metrics Campaign",
                status="active",
                selected_channels=["email", "sms"],
            )
        finally:
            conn.close()

        metrics_response = self.client.get("/api/simulations/campaigns/{}/metrics".format(campaign["id"]))
        metrics_payload = metrics_response.get_json()
        self.assertEqual(metrics_response.status_code, 200)
        self.assertEqual(metrics_payload["metrics"]["aggregate"]["total_targets"], 0)
        self.assertEqual(metrics_payload["metrics"]["aggregate"]["delivered_rate"], 0.0)

        targets_response = self.client.get("/api/simulations/campaigns/{}/targets/metrics".format(campaign["id"]))
        targets_payload = targets_response.get_json()
        self.assertEqual(targets_response.status_code, 200)
        self.assertEqual(targets_payload["targets"], [])

        csv_response = self.client.get("/simulations/campaigns/{}/targets/metrics.csv".format(campaign["id"]))
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn(b"campaign_id,campaign_name,target_id,display_name", csv_response.data)
        self.assertNotIn(b"Empty Metrics Campaign,", csv_response.data)

        json_response = self.client.get("/simulations/campaigns/{}/events.json".format(campaign["id"]))
        events_payload = json.loads(json_response.data.decode("utf-8"))
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(events_payload["events"], [])

        report_response = self.client.get("/simulations/campaigns/{}/report".format(campaign["id"]))
        self.assertEqual(report_response.status_code, 200)
        self.assertIn(b"Empty Metrics Campaign", report_response.data)
        self.assertIn(b"No channel metrics match the current filters.", report_response.data)
        self.assertIn(b"No target metrics match the current filters.", report_response.data)
        self.assertIn(b"No events recorded yet.", report_response.data)

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

    def test_events_api_returns_structured_validation_errors(self):
        response = self.client.post(
            "/api/simulations/events",
            json={
                "campaign_id": self._campaign_id(),
                "event_type": "attachment_open",
                "channel": "fax",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["type"], "simulation_event_record_error")
        self.assertIn("channel must be one of", payload["error"]["message"])

    def test_delivery_routes_preview_start_and_render_status(self):
        campaign_id = self._campaign_id()

        preview_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/preview".format(campaign_id),
            json={"mode": "dry_run"},
        )
        preview_payload = preview_response.get_json()

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_payload["status"], "ok")
        self.assertEqual(preview_payload["preview"]["mode"], "dry_run")
        self.assertEqual(preview_payload["preview"]["total_targets"], 4)
        self.assertEqual(set(preview_payload["preview"]["providers"].keys()), {"email", "sms", "voice"})
        self.assertEqual(preview_payload["preview"]["providers"]["email"]["provider_key"], "dry_run_email")

        start_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={"mode": "dry_run", "max_retries": 0},
        )
        start_payload = start_response.get_json()
        job_id = start_payload["delivery"]["job"]["id"]

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_payload["status"], "ok")
        self.assertEqual(start_payload["delivery"]["job"]["status"], "completed")
        self.assertEqual(start_payload["delivery"]["job"]["delivered_count"], 4)
        self.assertEqual(len(start_payload["delivery"]["attempts"]), 4)
        self.assertEqual(len(start_payload["delivery"]["tracking_tokens"]), 12)
        self.assertNotIn("route-pass", str(start_payload))

        api_response = self.client.get("/api/simulations/deliveries/{}".format(job_id))
        api_payload = api_response.get_json()

        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_payload["status"], "ok")
        self.assertEqual(api_payload["delivery"]["job"]["id"], job_id)
        self.assertEqual(api_payload["delivery"]["job"]["mode"], "dry_run")

        page_response = self.client.get("/simulations/deliveries/{}".format(job_id))

        self.assertEqual(page_response.status_code, 200)
        self.assertIn(b"Delivery Job #", page_response.data)
        self.assertIn(b"Dry-run delivery recorded attempts", page_response.data)
        self.assertIn(b"Provider Snapshot", page_response.data)
        self.assertIn(b"Delivery Attempts", page_response.data)
        self.assertIn(b"Tracking Tokens", page_response.data)

        detail_response = self.client.get("/simulations/campaigns/{}".format(campaign_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Delivery #{}".format(job_id).encode("utf-8"), detail_response.data)
        self.assertIn(b"delivered", detail_response.data)
        self.assertIn(b"Latest Event", detail_response.data)

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign_id)]
        self.assertIn("delivery.preview", audit_actions)
        self.assertIn("delivery.start", audit_actions)

    def test_delivery_start_blocks_campaign_without_authorization_statement(self):
        conn = sqlite3.connect(self.db_path)
        try:
            campaign = create_campaign(conn, "Route Readiness Block", selected_channels=["email"])
            create_target(
                conn,
                campaign["id"],
                name="Blocked Target",
                email="blocked.target@example.test",
                channel="email",
            )
        finally:
            conn.close()

        response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign["id"]),
            json={"mode": "dry_run", "max_retries": 0},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["type"], "delivery_readiness_failed")
        self.assertFalse(payload["error"]["readiness"]["ready"])
        failed_keys = {
            check["key"]
            for check in payload["error"]["readiness"]["failed_checks"]
        }
        self.assertIn("authorization_statement", failed_keys)

    def test_delivery_routes_return_structured_errors(self):
        missing_status = self.client.get("/api/simulations/deliveries/999999")
        missing_payload = missing_status.get_json()

        self.assertEqual(missing_status.status_code, 404)
        self.assertEqual(missing_payload["error"]["type"], "delivery_status_error")

        missing_preview = self.client.post(
            "/simulations/campaigns/999999/deliveries/preview",
            json={"mode": "dry_run"},
        )
        missing_preview_payload = missing_preview.get_json()

        self.assertEqual(missing_preview.status_code, 400)
        self.assertEqual(missing_preview_payload["error"]["type"], "delivery_preview_error")

        bad_mode = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(self._campaign_id()),
            json={"mode": "immediate"},
        )
        bad_mode_payload = bad_mode.get_json()

        self.assertEqual(bad_mode.status_code, 400)
        self.assertEqual(bad_mode_payload["error"]["type"], "delivery_start_error")
        self.assertIn("Delivery mode must be dry_run or provider", bad_mode_payload["error"]["message"])

    def test_delivery_start_with_disabled_provider_reports_failed_attempts(self):
        campaign_id = self._campaign_id()
        smtp_provider_id = self._delivery_provider_id("smtp_email")

        response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={
                "mode": "provider",
                "provider_ids": {"email": smtp_provider_id},
                "max_retries": 0,
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["type"], "delivery_readiness_failed")
        self.assertIn("Enable the SMTP Email provider", payload["error"]["message"])
        self.assertNotIn("route-pass", str(payload))

    def test_delivery_start_with_incomplete_enabled_provider_reports_configuration_error(self):
        campaign_id = self._campaign_id()
        sms_provider_id = self._delivery_provider_id("sms_api")
        settings_response = self.client.post(
            "/api/delivery-settings",
            json={
                "provider_id": sms_provider_id,
                "enabled": True,
                "setting_sender_id": "TRAINING",
            },
        )

        response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={
                "mode": "provider",
                "provider_ids": {"sms": sms_provider_id},
                "max_retries": 0,
            },
        )
        payload = response.get_json()

        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["type"], "delivery_readiness_failed")
        self.assertIn("Configure credentials for SMS API", payload["error"]["message"])

    def test_tracking_endpoints_record_open_link_and_attachment_events(self):
        campaign_id = self._campaign_id()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE simulation_campaigns SET training_url = ? WHERE id = ?",
                ("https://training.example.test/module", campaign_id),
            )
            conn.commit()
        finally:
            conn.close()
        start_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={"mode": "dry_run"},
        )
        delivery = start_response.get_json()["delivery"]
        open_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "open")
        link_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "link")
        attachment_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "attachment")

        open_response = self.client.get("/simulations/track/open/{}".format(open_token["token"]))
        link_response = self.client.get("/simulations/track/link/{}".format(link_token["token"]))
        attachment_response = self.client.post("/simulations/track/attachment/{}".format(attachment_token["token"]))
        attachment_payload = attachment_response.get_json()

        self.assertEqual(open_response.status_code, 200)
        self.assertEqual(open_response.mimetype, "image/gif")
        self.assertEqual(link_response.status_code, 302)
        self.assertEqual(link_response.headers["Location"], "https://training.example.test/module")
        self.assertEqual(attachment_response.status_code, 200)
        self.assertEqual(attachment_payload["event"]["event_type"], "attachment_open")

        conn = sqlite3.connect(self.db_path)
        try:
            event_rows = conn.execute(
                """
                SELECT event_type
                FROM simulation_events
                WHERE tracking_token_id IN (?, ?, ?)
                ORDER BY id ASC
                """,
                (open_token["id"], link_token["id"], attachment_token["id"]),
            ).fetchall()
            token_counts = conn.execute(
                """
                SELECT SUM(event_count)
                FROM simulation_tracking_tokens
                WHERE id IN (?, ?, ?)
                """,
                (open_token["id"], link_token["id"], attachment_token["id"]),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual([row[0] for row in event_rows], ["opened", "link_click", "attachment_open"])
        self.assertEqual(token_counts, 3)

    def test_provider_webhook_records_event_and_validates_configured_signature(self):
        campaign_id = self._campaign_id()
        start_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={"mode": "dry_run"},
        )
        token = next(
            item for item in start_response.get_json()["delivery"]["tracking_tokens"]
            if item["token_type"] == "open"
        )
        body = json.dumps({
            "token": token["token"],
            "event_type": "opened",
            "provider_event_id": "evt-route-test",
        }).encode("utf-8")

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE simulation_channel_providers
                SET settings_json = ?
                WHERE channel = 'email' AND provider_key = 'dry_run_email'
                """,
                (json.dumps({"webhook_secret": "route-secret"}),),
            )
            conn.commit()
        finally:
            conn.close()

        rejected = self.client.post(
            "/api/simulations/providers/email/dry_run_email/webhook",
            data=body,
            content_type="application/json",
            headers={"X-SocialFish-Signature": "bad-signature"},
        )
        signature = hmac.new(b"route-secret", body, hashlib.sha256).hexdigest()
        accepted = self.client.post(
            "/api/simulations/providers/email/dry_run_email/webhook",
            data=body,
            content_type="application/json",
            headers={"X-SocialFish-Signature": "sha256={}".format(signature)},
        )
        accepted_payload = accepted.get_json()

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted_payload["status"], "ok")
        self.assertEqual(accepted_payload["event"]["event_type"], "opened")
        self.assertEqual(accepted_payload["provider"]["provider_key"], "dry_run_email")

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

    def test_delivery_settings_api_updates_provider_without_echoing_secret(self):
        conn = sqlite3.connect(self.db_path)
        try:
            provider_id = conn.execute(
                "SELECT id FROM simulation_channel_providers WHERE provider_key = 'smtp_email'"
            ).fetchone()[0]
        finally:
            conn.close()

        response = self.client.post(
            "/api/delivery-settings",
            json={
                "provider_id": provider_id,
                "provider_name": "Route SMTP Provider",
                "enabled": True,
                "setting_smtp_host": "smtp.example.test",
                "setting_smtp_port": "587",
                "setting_from_email": "training@example.test",
                "secret": "delivery-secret-route-test",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["provider"]["provider_name"], "Route SMTP Provider")
        self.assertTrue(payload["provider"]["enabled"])
        self.assertEqual(payload["provider"]["settings"]["smtp_host"], "smtp.example.test")
        self.assertTrue(payload["provider"]["secret_configured"])
        self.assertNotIn("secret_placeholder", payload["provider"])
        self.assertNotIn("delivery-secret-route-test", str(payload))

    def test_directory_settings_routes_create_test_and_list_groups_without_echoing_secret(self):
        empty_page = self.client.get("/integrations/directory")
        self.assertEqual(empty_page.status_code, 200)
        self.assertIn(b"Directory Provider Settings", empty_page.data)
        self.assertIn(b"No directory providers have been configured yet.", empty_page.data)
        self.assertIn(b"Add Directory Provider", empty_page.data)
        self.assertIn(b"Mock Entra", empty_page.data)
        self.assertIn(b"Microsoft Graph Permissions", empty_page.data)
        self.assertIn(b"Group.Read.All", empty_page.data)
        self.assertIn(b"Sync History", empty_page.data)

        create_response = self.client.post(
            "/api/integrations/directory/providers",
            json={
                "name": "Route Mock Entra",
                "provider_type": "mock_entra",
                "enabled": True,
                "consent_status": "granted",
                "selected_groups": ["group-finance"],
                "secret": "directory-secret-route-test",
            },
        )
        created = create_response.get_json()
        provider_id = created["provider"]["id"]

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(created["status"], "ok")
        self.assertEqual(created["provider"]["name"], "Route Mock Entra")
        self.assertTrue(created["provider"]["enabled"])
        self.assertTrue(created["provider"]["secret_configured"])
        self.assertEqual(created["provider"]["selected_groups"], ["group-finance"])
        self.assertNotIn("secret_placeholder", created["provider"])
        self.assertNotIn("directory-secret-route-test", str(created))

        settings_page = self.client.get("/integrations/directory")
        self.assertEqual(settings_page.status_code, 200)
        self.assertIn(b"Route Mock Entra", settings_page.data)
        self.assertIn(b"group-finance", settings_page.data)
        self.assertIn(b"Secret placeholder: configured", settings_page.data)
        self.assertIn(b"Group Selection", settings_page.data)
        self.assertIn(b"Sync Preview", settings_page.data)
        self.assertIn(b"Confirm Import", settings_page.data)
        self.assertIn(b"Default campaign", settings_page.data)
        self.assertNotIn(b"directory-secret-route-test", settings_page.data)

        test_response = self.client.post(
            "/api/integrations/directory/providers/{}/test".format(provider_id),
            json={},
        )
        test_payload = test_response.get_json()
        self.assertEqual(test_response.status_code, 200)
        self.assertEqual(test_payload["status"], "ok")
        self.assertEqual(test_payload["test"]["group_count"], 3)
        self.assertTrue(test_payload["test"]["mock"])

        groups_response = self.client.get(
            "/api/integrations/directory/providers/{}/groups".format(provider_id)
        )
        groups_payload = groups_response.get_json()
        self.assertEqual(groups_response.status_code, 200)
        self.assertEqual(groups_payload["status"], "ok")
        self.assertEqual(
            [group["external_group_id"] for group in groups_payload["groups"]],
            ["group-finance", "group-engineering", "group-operations"],
        )
        self.assertNotIn("directory-secret-route-test", str(groups_payload))

        update_response = self.client.post(
            "/api/integrations/directory/providers",
            json={
                "provider_id": provider_id,
                "name": "Route Mock Entra Updated",
                "provider_type": "mock_entra",
                "enabled": True,
                "selected_groups": ["group-engineering"],
            },
        )
        updated = update_response.get_json()
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(updated["provider"]["name"], "Route Mock Entra Updated")
        self.assertEqual(updated["provider"]["selected_groups"], ["group-engineering"])
        self.assertTrue(updated["provider"]["secret_configured"])

        admin_events = self._administrative_audit_events()
        admin_actions = [event["action_type"] for event in admin_events]
        self.assertIn("directory_provider.create", admin_actions)
        self.assertIn("directory_provider.test", admin_actions)
        self.assertIn("directory_provider.update", admin_actions)
        create_events = [event for event in admin_events if event["action_type"] == "directory_provider.create"]
        self.assertEqual(create_events[0]["metadata"]["request"]["secret"], "[redacted]")

    def test_directory_graph_route_fails_safely_with_actionable_error(self):
        create_response = self.client.post(
            "/api/integrations/directory/providers",
            json={
                "name": "Route Graph Shell",
                "provider_type": "microsoft_graph",
                "enabled": True,
            },
        )
        provider_id = create_response.get_json()["provider"]["id"]

        test_response = self.client.post(
            "/api/integrations/directory/providers/{}/test".format(provider_id),
            json={},
        )
        groups_response = self.client.get(
            "/api/integrations/directory/providers/{}/groups".format(provider_id)
        )
        preview_response = self.client.post(
            "/api/integrations/directory/providers/{}/preview".format(provider_id),
            json={"group_ids": ["graph-group-placeholder"]},
        )
        test_payload = test_response.get_json()
        payload = groups_response.get_json()
        preview_payload = preview_response.get_json()

        self.assertEqual(test_response.status_code, 400)
        self.assertEqual(test_payload["status"], "error")
        self.assertEqual(test_payload["error"]["type"], "directory_provider_configuration")
        self.assertIn("tenant_id", test_payload["error"]["message"])
        self.assertEqual(groups_response.status_code, 400)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["type"], "directory_provider_configuration")
        self.assertIn("tenant_id", payload["error"]["message"])
        self.assertEqual(preview_response.status_code, 400)
        self.assertEqual(preview_payload["status"], "error")
        self.assertEqual(preview_payload["error"]["type"], "directory_provider_configuration")
        self.assertIn("tenant_id", preview_payload["error"]["message"])

    def test_directory_preview_sync_job_and_import_routes_preserve_audit_history(self):
        conn = sqlite3.connect(self.db_path)
        try:
            import_campaign = create_campaign(conn, "Directory Route Import Campaign", selected_channels=["email"])
            campaign_id = import_campaign["id"]
        finally:
            conn.close()
        create_response = self.client.post(
            "/api/integrations/directory/providers",
            json={
                "name": "Route Sync Mock Entra",
                "provider_type": "mock_entra",
                "enabled": True,
                "consent_status": "granted",
                "selected_groups": ["group-engineering"],
            },
        )
        provider_id = create_response.get_json()["provider"]["id"]

        preview_response = self.client.post(
            "/api/integrations/directory/providers/{}/preview".format(provider_id),
            json={"group_ids": ["group-finance"]},
        )
        preview_payload = preview_response.get_json()

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_payload["status"], "ok")
        self.assertEqual(preview_payload["sync_job"]["job"]["job_type"], "preview")
        self.assertEqual(preview_payload["sync_job"]["job"]["staged_count"], 2)
        self.assertEqual(preview_payload["sync_job"]["job"]["imported_count"], 0)
        self.assertEqual(
            [user["external_user_id"] for user in preview_payload["sync_job"]["staged_users"]],
            ["mock-user-avery-stone", "mock-user-morgan-patel"],
        )
        self.assertEqual(
            [event["event_type"] for event in preview_payload["sync_job"]["audit_events"]],
            ["preview_started", "preview_completed"],
        )

        conn = sqlite3.connect(self.db_path)
        try:
            preview_imports = conn.execute(
                "SELECT COUNT(*) FROM simulation_targets WHERE source = 'directory'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(preview_imports, 0)

        sync_response = self.client.post(
            "/api/integrations/directory/providers/{}/sync".format(provider_id),
            json={"group_ids": ["group-engineering"], "campaign_id": campaign_id},
        )
        sync_payload = sync_response.get_json()
        sync_job_id = sync_payload["sync_job"]["job"]["id"]

        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(sync_payload["status"], "ok")
        self.assertEqual(sync_payload["sync_job"]["job"]["job_type"], "sync")
        self.assertEqual(sync_payload["sync_job"]["job"]["staged_count"], 2)
        self.assertEqual(sync_payload["sync_job"]["job"]["imported_count"], 2)
        self.assertEqual(sync_payload["sync_job"]["job"]["skipped_count"], 0)
        self.assertTrue(all(user["imported_target_id"] for user in sync_payload["sync_job"]["staged_users"]))
        self.assertEqual(
            [event["event_type"] for event in sync_payload["sync_job"]["audit_events"]],
            ["sync_started", "sync_completed"],
        )

        job_page = self.client.get("/integrations/directory/sync-jobs/{}".format(sync_job_id))
        self.assertEqual(job_page.status_code, 200)
        self.assertIn(b"Directory Sync Job", job_page.data)
        self.assertIn(b"sync_completed", job_page.data)
        self.assertIn(b"Riley Chen", job_page.data)

        history_page = self.client.get("/integrations/directory")
        self.assertEqual(history_page.status_code, 200)
        self.assertIn(b"Sync History", history_page.data)
        self.assertIn("/integrations/directory/sync-jobs/{}".format(sync_job_id).encode(), history_page.data)

        campaign_page = self.client.get(
            "/simulations/campaigns/{}?source=directory&department=Engineering&group=group-engineering#targets".format(
                campaign_id
            )
        )
        self.assertEqual(campaign_page.status_code, 200)
        self.assertIn(b"Directory Group", campaign_page.data)
        self.assertIn(b"Engineering Awareness Pilot", campaign_page.data)
        self.assertIn(b"mock-user-riley-chen", campaign_page.data)
        self.assertIn(b"source", campaign_page.data)
        self.assertIn(b"directory", campaign_page.data)

        duplicate_response = self.client.post(
            "/api/integrations/directory/providers/{}/sync".format(provider_id),
            json={"group_ids": ["group-engineering"], "campaign_id": campaign_id},
        )
        duplicate_payload = duplicate_response.get_json()

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(duplicate_payload["sync_job"]["job"]["imported_count"], 0)
        self.assertEqual(duplicate_payload["sync_job"]["job"]["duplicate_count"], 2)
        self.assertEqual(duplicate_payload["sync_job"]["job"]["skipped_count"], 2)

        conn = sqlite3.connect(self.db_path)
        try:
            imported = conn.execute(
                """
                SELECT name, email, source, campaign_id, source_reference, source_metadata_json
                FROM simulation_targets
                WHERE source = 'directory'
                ORDER BY name ASC
                """
            ).fetchall()
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM directory_sync_audit_events"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(len(imported), 2)
        self.assertEqual([row[0] for row in imported], ["Morgan Patel", "Riley Chen"])
        self.assertTrue(all(row[2] == "directory" and row[3] == campaign_id for row in imported))
        self.assertTrue(all(row[4].startswith("mock-user-") for row in imported))
        self.assertTrue(all("group-engineering" in row[5] for row in imported))
        self.assertEqual(audit_count, 6)

        admin_actions = [event["action_type"] for event in self._administrative_audit_events()]
        self.assertIn("directory_provider.create", admin_actions)
        self.assertIn("directory_sync.preview", admin_actions)
        self.assertIn("directory_sync.sync", admin_actions)

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
                "authorization_statement": "Cybersecurity authorized this route-managed campaign for internal testing.",
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

        list_response = self.client.get("/simulations/campaigns")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(b"Route Managed Campaign", list_response.data)
        self.assertIn(b"email", list_response.data)
        self.assertIn(b"sms", list_response.data)

        detail_response = self.client.get("/simulations/campaigns/{}".format(campaign_id))
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b"Delivery", detail_response.data)
        self.assertIn(b"Campaign Metrics", detail_response.data)
        self.assertIn(b"Event source labels", detail_response.data)
        self.assertIn(b"Per-Channel Status", detail_response.data)
        self.assertIn(b"Target Activity History", detail_response.data)
        self.assertIn(b"Filtered View", detail_response.data)
        self.assertIn(b"Dry-run", detail_response.data)
        self.assertIn(b"Simulated", detail_response.data)
        self.assertIn(b"Dry-run mode is selected by default.", detail_response.data)
        self.assertIn(b"Start Dry-run Delivery", detail_response.data)
        self.assertIn(b"Recent Delivery Jobs", detail_response.data)
        self.assertIn(b"Provider Settings", detail_response.data)
        self.assertIn(b"/ai-settings#delivery-providers", detail_response.data)
        self.assertIn(b"Audit Events", detail_response.data)
        self.assertIn(b"/audit-log?campaign_id=", detail_response.data)
        self.assertIn(b"Edit Campaign", detail_response.data)
        self.assertIn(b"Add Targets", detail_response.data)
        self.assertIn(b"Manual Target Entry", detail_response.data)
        self.assertIn(b"CSV Upload", detail_response.data)
        self.assertIn(b"Required columns", detail_response.data)
        self.assertIn(b"Optional columns", detail_response.data)
        self.assertIn(b"Download Sample CSV", detail_response.data)
        self.assertIn(b"/simulations/targets/sample.csv", detail_response.data)
        self.assertIn(b"Unknown columns are reported as validation errors.", detail_response.data)
        self.assertIn(b'name="targets_csv"', detail_response.data)
        self.assertIn(b"Targets", detail_response.data)
        self.assertIn(b"All sources", detail_response.data)
        self.assertIn(b"All departments", detail_response.data)
        self.assertIn(b"Directory Group", detail_response.data)
        self.assertIn(b"Events", detail_response.data)
        self.assertIn(b"Archive", detail_response.data)
        self.assertIn(b"AI Draft History", detail_response.data)
        self.assertIn(b"No AI drafts have been saved for this campaign yet.", detail_response.data)
        self.assertIn(b"/simulations/ai-builder?campaign_id=", detail_response.data)
        self.assertIn(b"/ai-settings", detail_response.data)

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
                "authorization_statement": "Cybersecurity reauthorized this route-managed campaign for FY26.",
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

        archived_list_response = self.client.get("/simulations/campaigns")
        self.assertEqual(archived_list_response.status_code, 200)
        self.assertNotIn(b"Route Managed Campaign FY26", archived_list_response.data)

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign_id)]
        self.assertEqual(audit_actions, ["campaign.create", "campaign.update", "campaign.archive"])

    def test_campaign_create_route_displays_validation_errors(self):
        response = self.client.post(
            "/simulations/campaigns",
            data={"name": "", "selected_channels": ["email"]},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Campaign name is required.", response.data)

    def test_campaign_routes_validate_dates_and_status_transitions(self):
        create_response = self.client.post(
            "/simulations/campaigns",
            data={
                "name": "Route Invalid Date Campaign",
                "status": "draft",
                "selected_channels": ["email"],
                "start_date": "2026/10/01",
                "authorization_statement": "Authorized internal validation test.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 400)
        self.assertIn(b"start_date must use YYYY-MM-DD format.", create_response.data)

        campaign_id = self._campaign_id()
        complete_response = self.client.post(
            "/simulations/campaigns/{}".format(campaign_id),
            data={
                "name": "Completed Route Campaign",
                "status": "completed",
                "selected_channels": ["email"],
                "authorization_statement": "Authorized internal validation test.",
            },
            follow_redirects=False,
        )
        archived_response = self.client.post(
            "/simulations/campaigns/{}".format(campaign_id),
            data={
                "name": "Archived Route Campaign",
                "status": "archived",
                "selected_channels": ["email"],
                "authorization_statement": "Authorized internal validation test.",
            },
            follow_redirects=True,
        )
        reactivate_response = self.client.post(
            "/simulations/campaigns/{}".format(campaign_id),
            data={
                "name": "Reactivated Route Campaign",
                "status": "active",
                "selected_channels": ["email"],
                "authorization_statement": "Authorized internal validation test.",
            },
            follow_redirects=True,
        )

        self.assertEqual(complete_response.status_code, 302)
        self.assertEqual(archived_response.status_code, 200)
        self.assertIn(b"Campaign status must be one of: draft, active, paused, completed", archived_response.data)
        self.assertEqual(reactivate_response.status_code, 200)
        self.assertIn(b"Campaign status cannot transition from completed to active.", reactivate_response.data)

    def test_simulation_admin_routes_require_login(self):
        anonymous_client = self.socialfish.app.test_client()
        campaign_id = self._campaign_id()
        provider_id = self._provider_id("local")
        protected_resource_id = 1
        protected_requests = [
            anonymous_client.get("/simulations"),
            anonymous_client.get("/simulations/campaigns"),
            anonymous_client.get("/simulations/campaigns/new"),
            anonymous_client.post("/simulations/campaigns", data={}),
            anonymous_client.get("/simulations/campaigns/{}".format(campaign_id)),
            anonymous_client.post("/simulations/campaigns/{}/archive".format(campaign_id)),
            anonymous_client.get("/simulations/ai-builder"),
            anonymous_client.get("/ai-settings"),
            anonymous_client.post("/api/ai-settings", json={}),
            anonymous_client.post("/api/delivery-settings", json={}),
            anonymous_client.get("/audit-log"),
            anonymous_client.get("/audit-log/1"),
            anonymous_client.get("/api/simulations/metrics"),
            anonymous_client.get("/api/simulations/metrics/overview"),
            anonymous_client.get("/api/simulations/campaigns/{}/metrics".format(campaign_id)),
            anonymous_client.get("/api/simulations/campaigns/{}/targets/metrics".format(campaign_id)),
            anonymous_client.get("/simulations/campaigns/{}/targets/metrics.csv".format(campaign_id)),
            anonymous_client.get("/simulations/campaigns/{}/events.json".format(campaign_id)),
            anonymous_client.get("/simulations/campaigns/{}/report".format(campaign_id)),
            anonymous_client.post("/api/simulations/events", json={}),
            anonymous_client.post("/api/simulations/ai/generate", json={"provider_id": provider_id}),
            anonymous_client.post("/api/simulations/ai/save-draft", json={}),
            anonymous_client.post("/simulations/campaigns/{}/deliveries/preview".format(campaign_id), json={}),
            anonymous_client.post("/simulations/campaigns/{}/deliveries/start".format(campaign_id), json={}),
            anonymous_client.get("/api/simulations/deliveries/1"),
            anonymous_client.get("/simulations/deliveries/1"),
            anonymous_client.get("/integrations/directory"),
            anonymous_client.post("/api/integrations/directory/providers", json={}),
            anonymous_client.post("/api/integrations/directory/providers/{}/test".format(protected_resource_id), json={}),
            anonymous_client.get("/api/integrations/directory/providers/{}/groups".format(protected_resource_id)),
            anonymous_client.post("/api/integrations/directory/providers/{}/preview".format(protected_resource_id), json={}),
            anonymous_client.post("/api/integrations/directory/providers/{}/sync".format(protected_resource_id), json={}),
            anonymous_client.get("/integrations/directory/sync-jobs/{}".format(protected_resource_id)),
        ]

        for response in protected_requests:
            self.assertIn(response.status_code, (200, 401, 302))
            self.assertIn(b"Unauthorized", response.data)
            self.assertNotIn(b"Campaign Management", response.data)

    def test_target_sample_csv_route_generates_download(self):
        response = self.client.get("/simulations/targets/sample.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn(
            "attachment; filename=simulation-target-import-sample.csv",
            response.headers["Content-Disposition"],
        )
        self.assertIn(
            b"name,display_name,email,phone,department,manager,channel,active\n",
            response.data,
        )
        self.assertIn(b"jordan.rivera@example.test", response.data)
        self.assertIn(b"+15551234567", response.data)
        self.assertNotIn(b"route-pass", response.data)

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

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign_id)]
        self.assertIn("target.create", audit_actions)
        self.assertIn("target.update", audit_actions)
        self.assertIn("target.archive", audit_actions)

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

        audit_events = self._administrative_audit_events(campaign_id)
        csv_events = [event for event in audit_events if event["action_type"] == "target.csv_import"]
        self.assertEqual(len(csv_events), 1)
        self.assertEqual(csv_events[0]["metadata"]["original_filename"], "route-targets.csv")
        self.assertEqual(csv_events[0]["metadata"]["imported_rows"], 2)

    def test_target_csv_upload_reports_duplicate_contacts(self):
        campaign_id = self._campaign_id()
        csv_content = (
            "name,email,phone,channel,department\n"
            "CSV Duplicate One,duplicate.route@example.test,,email,Security\n"
            "CSV Duplicate Two,duplicate.route@example.test,,email,Security\n"
        )

        response = self.client.post(
            "/simulations/campaigns/{}/targets/upload".format(campaign_id),
            data={
                "targets_csv": (
                    io.BytesIO(csv_content.encode("utf-8")),
                    "duplicate-targets.csv",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Imported 1 target(s) with 1 validation error(s).", response.data)
        self.assertIn(b"CSV row 3: Duplicate target contact in CSV.", response.data)
        self.assertIn(b"Row 3: Duplicate target contact in CSV.", response.data)

        conn = sqlite3.connect(self.db_path)
        try:
            imported = conn.execute(
                """
                SELECT COUNT(*)
                FROM simulation_targets
                WHERE campaign_id = ?
                    AND source = 'csv'
                    AND email = 'duplicate.route@example.test'
                """,
                (campaign_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(imported, 1)

    def test_full_simulation_workflow_regression(self):
        anonymous_client = self.socialfish.app.test_client()
        anonymous_campaigns = anonymous_client.get("/simulations/campaigns")
        anonymous_metrics = anonymous_client.get("/api/simulations/metrics")
        self.assertIn(anonymous_campaigns.status_code, (200, 401, 302))
        self.assertIn(b"Unauthorized", anonymous_campaigns.data)
        self.assertIn(anonymous_metrics.status_code, (200, 401, 302))
        self.assertIn(b"Unauthorized", anonymous_metrics.data)

        create_campaign_response = self.client.post(
            "/simulations/campaigns",
            data={
                "name": "Workflow Regression Campaign",
                "description": "End-to-end workflow coverage",
                "objective": "Practice reporting suspicious payment requests",
                "training_owner": "Security Awareness",
                "status": "active",
                "selected_channels": ["email", "sms", "voice"],
                "landing_url": "https://training.example.test/landing",
                "training_url": "https://training.example.test/course",
                "authorized_scope": "Internal employees in the regression cohort",
                "authorization_statement": "Security leadership authorized this internal training regression.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_campaign_response.status_code, 302)

        campaign_id = int(create_campaign_response.headers["Location"].rstrip("/").split("/")[-1])
        manual_response = self.client.post(
            "/simulations/campaigns/{}/targets".format(campaign_id),
            data={
                "name": "Workflow Manual Target",
                "display_name": "Workflow Manual",
                "email": "workflow.manual@example.test",
                "department": "Finance",
                "manager": "Avery Stone",
                "channel": "email",
                "active": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(manual_response.status_code, 200)
        self.assertIn(b"Target Workflow Manual added to the campaign.", manual_response.data)

        csv_content = (
            "name,email,phone,channel,department\n"
            "Workflow CSV SMS,,+15550107777,sms,Operations\n"
            "Workflow CSV Voice,,+15550108888,voice,Support\n"
        )
        csv_response = self.client.post(
            "/simulations/campaigns/{}/targets/upload".format(campaign_id),
            data={
                "targets_csv": (
                    io.BytesIO(csv_content.encode("utf-8")),
                    "workflow-targets.csv",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn(b"Imported 2 target(s) from CSV.", csv_response.data)

        provider_id = self._provider_id("local")
        generate_response = self.client.post(
            "/api/simulations/ai/generate",
            json={
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "scenario_goal": "Practice reporting suspicious payment requests",
                "audience": "Finance, operations, and support teams",
                "channels": ["email", "sms", "voice"],
                "tone": "calm",
                "difficulty": "standard",
                "training_reminder": "Use the report button before taking action.",
            },
        )
        self.assertEqual(generate_response.status_code, 200)
        generation = generate_response.get_json()["generation"]
        self.assertEqual(set(generation["channels"]), {"email", "sms", "voice"})

        save_response = self.client.post(
            "/api/simulations/ai/save-draft",
            json={
                "campaign_id": campaign_id,
                "provider": generation["provider"],
                "channels": generation["channels"],
                "draft": generation["draft"],
                "risk_flags": generation["risk_flags"],
                "safety_notes": generation["safety_notes"],
                "metadata": generation["metadata"],
                "audit_id": generation["administrative_audit_event_id"],
            },
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.get_json()["draft"]["campaign_id"], campaign_id)

        preview_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/preview".format(campaign_id),
            json={"mode": "dry_run"},
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["preview"]["total_attempts"], 3)

        start_response = self.client.post(
            "/simulations/campaigns/{}/deliveries/start".format(campaign_id),
            json={"mode": "dry_run"},
        )
        self.assertEqual(start_response.status_code, 200)
        delivery = start_response.get_json()["delivery"]
        job_id = delivery["job"]["id"]
        self.assertEqual(delivery["job"]["status"], "completed")
        self.assertEqual(delivery["job"]["delivered_count"], 3)
        self.assertEqual(len(delivery["tracking_tokens"]), 9)

        open_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "open")
        link_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "link")
        attachment_token = next(token for token in delivery["tracking_tokens"] if token["token_type"] == "attachment")
        open_response = anonymous_client.get("/simulations/track/open/{}".format(open_token["token"]))
        link_response = anonymous_client.get("/simulations/track/link/{}".format(link_token["token"]))
        attachment_response = anonymous_client.post("/simulations/track/attachment/{}".format(attachment_token["token"]))
        self.assertEqual(open_response.status_code, 200)
        self.assertEqual(open_response.mimetype, "image/gif")
        self.assertEqual(link_response.status_code, 302)
        self.assertEqual(link_response.headers["Location"], "https://training.example.test/course")
        self.assertEqual(attachment_response.status_code, 200)
        self.assertEqual(attachment_response.get_json()["status"], "ok")

        metrics_response = self.client.get("/api/simulations/campaigns/{}/metrics".format(campaign_id))
        targets_metrics_response = self.client.get(
            "/api/simulations/campaigns/{}/targets/metrics".format(campaign_id)
        )
        metrics_csv_response = self.client.get(
            "/simulations/campaigns/{}/targets/metrics.csv".format(campaign_id)
        )
        events_export_response = self.client.get("/simulations/campaigns/{}/events.json".format(campaign_id))
        self.assertEqual(metrics_response.status_code, 200)
        self.assertEqual(metrics_response.get_json()["metrics"]["aggregate"]["delivered"], 3)
        self.assertEqual(metrics_response.get_json()["metrics"]["aggregate"]["opened"], 1)
        self.assertEqual(targets_metrics_response.status_code, 200)
        self.assertEqual(len(targets_metrics_response.get_json()["targets"]), 3)
        self.assertEqual(metrics_csv_response.status_code, 200)
        self.assertIn(b"workflow.manual@example.test", metrics_csv_response.data)
        self.assertEqual(events_export_response.status_code, 200)
        self.assertEqual(events_export_response.get_json()["campaign"]["id"], campaign_id)

        directory_response = self.client.post(
            "/api/integrations/directory/providers",
            json={
                "name": "Workflow Mock Entra",
                "provider_type": "mock_entra",
                "enabled": True,
                "consent_status": "granted",
                "selected_groups": ["group-finance"],
            },
        )
        self.assertEqual(directory_response.status_code, 200)
        directory_provider_id = directory_response.get_json()["provider"]["id"]

        directory_preview_response = self.client.post(
            "/api/integrations/directory/providers/{}/preview".format(directory_provider_id),
            json={"group_ids": ["group-finance"]},
        )
        self.assertEqual(directory_preview_response.status_code, 200)
        self.assertEqual(directory_preview_response.get_json()["sync_job"]["job"]["staged_count"], 2)

        directory_sync_response = self.client.post(
            "/api/integrations/directory/providers/{}/sync".format(directory_provider_id),
            json={"group_ids": ["group-finance"], "campaign_id": campaign_id},
        )
        self.assertEqual(directory_sync_response.status_code, 200)
        self.assertEqual(directory_sync_response.get_json()["sync_job"]["job"]["imported_count"], 2)

        delivery_status_response = self.client.get("/api/simulations/deliveries/{}".format(job_id))
        self.assertEqual(delivery_status_response.status_code, 200)
        self.assertEqual(delivery_status_response.get_json()["delivery"]["job"]["id"], job_id)

        conn = sqlite3.connect(self.db_path)
        try:
            target_sources = {
                row[0]: row[1]
                for row in conn.execute(
                    """
                    SELECT source, COUNT(*)
                    FROM simulation_targets
                    WHERE campaign_id = ?
                    GROUP BY source
                    """,
                    (campaign_id,),
                )
            }
        finally:
            conn.close()
        self.assertEqual(target_sources, {"csv": 2, "directory": 2, "manual": 1})

        audit_actions = [event["action_type"] for event in self._administrative_audit_events(campaign_id)]
        for expected_action in (
            "campaign.create",
            "target.create",
            "target.csv_import",
            "generation.create",
            "generation.draft_save",
            "delivery.preview",
            "delivery.start",
            "export.metrics",
            "export.events",
            "directory_sync.sync",
        ):
            self.assertIn(expected_action, audit_actions)


if __name__ == "__main__":
    unittest.main()
