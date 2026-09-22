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

    def test_authenticated_pages_render(self):
        simulations = self.client.get("/simulations")
        campaigns = self.client.get("/simulations/campaigns")
        new_campaign = self.client.get("/simulations/campaigns/new")
        ai_settings = self.client.get("/ai-settings")
        ai_builder = self.client.get("/simulations/ai-builder")

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

        list_response = self.client.get("/simulations/campaigns")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(b"Route Managed Campaign", list_response.data)
        self.assertIn(b"email", list_response.data)
        self.assertIn(b"sms", list_response.data)

        detail_response = self.client.get("/simulations/campaigns/{}".format(campaign_id))
        self.assertEqual(detail_response.status_code, 200)
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

    def test_campaign_create_route_displays_validation_errors(self):
        response = self.client.post(
            "/simulations/campaigns",
            data={"name": "", "selected_channels": ["email"]},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Campaign name is required.", response.data)

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


if __name__ == "__main__":
    unittest.main()
