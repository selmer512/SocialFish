import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.audit_service import (
    REDACTED_VALUE,
    audit_filter_options,
    get_audit_event,
    list_audit_events,
    record_ai_provider_audit,
    record_campaign_audit,
    record_delivery_audit,
    record_directory_sync_audit,
    record_export_audit,
    record_generation_audit,
    record_target_audit,
    redact_audit_metadata,
)
from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db


class AuditServiceTest(unittest.TestCase):
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

    def test_record_campaign_audit_redacts_plaintext_secret_metadata(self):
        audit_id = record_campaign_audit(
            self.conn,
            "campaign.create",
            self.campaign_id,
            actor_identity="operator@example.test",
            channel="email",
            ip_address="127.0.0.1",
            user_agent="UnitTest",
            metadata={
                "name": "Quarterly Training",
                "api_key": "sk-live-plaintext",
                "nested": {
                    "password": "correct horse battery staple",
                    "secret_reference": "vault://simulation/provider",
                    "secret_placeholder": "configured",
                },
                "targets": [
                    {"email": "avery@example.test", "session_token": "abc123"},
                ],
            },
        )

        events = list_audit_events(self.conn, campaign_id=self.campaign_id)
        self.assertEqual(events[0]["id"], audit_id)
        self.assertEqual(events[0]["actor_identity"], "operator@example.test")
        self.assertEqual(events[0]["action_type"], "campaign.create")
        self.assertEqual(events[0]["entity_type"], "campaign")
        self.assertEqual(events[0]["entity_id"], str(self.campaign_id))
        self.assertEqual(events[0]["channel"], "email")
        self.assertEqual(events[0]["ip_address"], "127.0.0.1")
        self.assertEqual(events[0]["user_agent"], "UnitTest")
        self.assertEqual(events[0]["metadata"]["name"], "Quarterly Training")
        self.assertEqual(events[0]["metadata"]["api_key"], REDACTED_VALUE)
        self.assertEqual(events[0]["metadata"]["nested"]["password"], REDACTED_VALUE)
        self.assertEqual(
            events[0]["metadata"]["nested"]["secret_reference"],
            "vault://simulation/provider",
        )
        self.assertEqual(events[0]["metadata"]["nested"]["secret_placeholder"], "configured")
        self.assertEqual(events[0]["metadata"]["targets"][0]["session_token"], REDACTED_VALUE)
        self.assertNotIn("sk-live-plaintext", str(events[0]))
        self.assertNotIn("correct horse battery staple", str(events[0]))

    def test_workflow_specific_helpers_record_expected_entity_types(self):
        helper_calls = [
            (record_target_audit, ("target.archive", 10), {"campaign_id": self.campaign_id}),
            (record_ai_provider_audit, ("ai_provider.configure", 11), {}),
            (record_generation_audit, ("generation.create", 12), {"campaign_id": self.campaign_id}),
            (record_delivery_audit, ("delivery.start", 13), {"campaign_id": self.campaign_id, "channel": "sms"}),
            (record_export_audit, ("export.metrics", "metrics-14"), {"campaign_id": self.campaign_id}),
            (record_directory_sync_audit, ("directory_sync.preview", 15), {"campaign_id": self.campaign_id}),
        ]

        for helper, args, kwargs in helper_calls:
            helper(self.conn, *args, actor_identity="operator@example.test", metadata={"ok": True}, **kwargs)

        entity_types = {
            event["action_type"]: event["entity_type"]
            for event in list_audit_events(self.conn, actor_identity="operator@example.test")
        }
        self.assertEqual(
            entity_types,
            {
                "target.archive": "target",
                "ai_provider.configure": "ai_provider",
                "generation.create": "ai_generation",
                "delivery.start": "delivery",
                "export.metrics": "export",
                "directory_sync.preview": "directory_sync",
            },
        )

    def test_redact_audit_metadata_handles_lists_and_safe_secret_references(self):
        payload = redact_audit_metadata(
            {
                "client_secret": "plaintext",
                "items": [
                    {"refresh_token": "token-value"},
                    {"secret_reference": "vault://safe/ref"},
                    {"secret_placeholder": "configured"},
                ],
            }
        )

        self.assertEqual(payload["client_secret"], REDACTED_VALUE)
        self.assertEqual(payload["items"][0]["refresh_token"], REDACTED_VALUE)
        self.assertEqual(payload["items"][1]["secret_reference"], "vault://safe/ref")
        self.assertEqual(payload["items"][2]["secret_placeholder"], "configured")

    def test_list_audit_events_filters_by_date_and_lookup_decodes_metadata(self):
        old_id = record_campaign_audit(
            self.conn,
            "campaign.create",
            self.campaign_id,
            actor_identity="operator@example.test",
            channel="email",
            metadata={"name": "Old"},
            occurred_at="2026-01-15T09:00:00",
        )
        new_id = record_delivery_audit(
            self.conn,
            "delivery.start",
            "job:1",
            campaign_id=self.campaign_id,
            actor_identity="operator@example.test",
            channel="sms",
            metadata={"mode": "dry_run"},
            occurred_at="2026-02-20T12:00:00",
        )

        filtered = list_audit_events(
            self.conn,
            campaign_id=self.campaign_id,
            start_date="2026-02-01",
            end_date="2026-02-28",
        )
        self.assertEqual([event["id"] for event in filtered], [new_id])

        detail = get_audit_event(self.conn, old_id)
        self.assertEqual(detail["metadata"], {"name": "Old"})

        options = audit_filter_options(self.conn)
        self.assertIn("campaign.create", options["action_types"])
        self.assertIn("delivery.start", options["action_types"])
        self.assertIn("campaign", options["entity_types"])
        self.assertIn("sms", options["channels"])
