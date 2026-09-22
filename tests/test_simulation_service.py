import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db
from core.ai_generation import AIContentPolicyError, AIScenarioRequest
from core.simulation_service import (
    archive_campaign,
    archive_target,
    create_campaign,
    create_target,
    get_campaign_detail,
    get_campaign_metrics,
    import_targets_csv,
    generate_ai_scenario,
    list_ai_generation_audits,
    list_ai_provider_settings,
    list_campaigns,
    list_simulation_events,
    list_targets,
    parse_target_csv,
    record_simulation_event,
    save_ai_campaign_draft,
    update_campaign,
    update_ai_provider_settings,
    update_target,
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

    def test_creates_updates_archives_and_details_campaigns(self):
        campaign = create_campaign(
            self.conn,
            "Finance Awareness",
            description="Internal finance training",
            objective="Reduce unsafe link clicks",
            training_owner="Security Team",
            selected_channels=["email", "sms"],
            landing_url="https://training.example.test/landing",
        )

        self.assertEqual(campaign["name"], "Finance Awareness")
        self.assertEqual(campaign["channel"], "email")
        self.assertEqual(campaign["selected_channels"], ["email", "sms"])
        self.assertFalse(campaign["archived"])

        updated = update_campaign(
            self.conn,
            campaign["id"],
            name="Finance Awareness FY26",
            status="active",
            selected_channels=["voice", "email"],
            training_url="https://training.example.test/course",
        )
        self.assertEqual(updated["slug"], "finance-awareness-fy26")
        self.assertEqual(updated["status"], "active")
        self.assertEqual(updated["channel"], "voice")
        self.assertEqual(updated["selected_channels"], ["voice", "email"])

        detail = get_campaign_detail(self.conn, campaign["id"])
        self.assertEqual(detail["campaign"]["id"], campaign["id"])
        self.assertEqual(detail["metrics"]["aggregate"]["total_targets"], 0)
        self.assertEqual(detail["targets"], [])

        archived = archive_campaign(self.conn, campaign["id"])
        self.assertTrue(archived["archived"])
        self.assertEqual(archived["status"], "archived")
        self.assertNotIn(campaign["id"], [row["id"] for row in list_campaigns(self.conn)])
        self.assertIn(campaign["id"], [row["id"] for row in list_campaigns(self.conn, include_archived=True)])

    def test_manual_targets_validate_update_and_archive(self):
        campaign = create_campaign(self.conn, "Target Service Test", selected_channels=["sms"])
        target = create_target(
            self.conn,
            campaign["id"],
            name="Taylor Gray",
            phone="(555) 010-2222",
            department="Finance",
            manager="Avery Stone",
        )

        self.assertEqual(target["phone"], "5550102222")
        self.assertEqual(target["channel"], "sms")
        self.assertTrue(target["active"])

        updated = update_target(
            self.conn,
            target["id"],
            channel="email",
            email="Taylor.Gray@Example.Test",
            phone="+1 555 010 2222",
            display_name="Taylor G.",
        )
        self.assertEqual(updated["email"], "taylor.gray@example.test")
        self.assertEqual(updated["phone"], "+15550102222")
        self.assertEqual(updated["display_name"], "Taylor G.")

        with self.assertRaisesRegex(ValueError, "valid address"):
            create_target(
                self.conn,
                campaign["id"],
                name="Invalid Email",
                email="not-an-email",
                channel="email",
            )

        archived = archive_target(self.conn, target["id"])
        self.assertFalse(archived["active"])
        self.assertTrue(archived["archived"])
        self.assertEqual(list_targets(self.conn, campaign["id"]), [])
        self.assertEqual(len(list_targets(self.conn, campaign["id"], include_archived=True)), 1)

    def test_parses_target_csv_with_displayable_validation_errors(self):
        parsed = parse_target_csv(
            """name,email,phone,channel,department
Valid Email,valid@example.test,,email,Finance
Missing Phone,,555,voice,Support
Bad Email,not-an-email,,email,Engineering
Duplicate Email,valid@example.test,,email,Finance
"""
        )

        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["email"], "valid@example.test")
        messages = [error["message"] for error in parsed["errors"]]
        self.assertTrue(any("7 to 15 digits" in message for message in messages))
        self.assertTrue(any("valid address" in message for message in messages))
        self.assertTrue(any("Duplicate target contact" in message for message in messages))
        self.assertEqual({error["row"] for error in parsed["errors"]}, {3, 4, 5})

    def test_imports_target_csv_and_records_batch_errors(self):
        campaign = create_campaign(self.conn, "CSV Import Test", selected_channels=["email", "sms"])
        create_target(
            self.conn,
            campaign["id"],
            name="Existing Target",
            email="existing@example.test",
            channel="email",
        )

        result = import_targets_csv(
            self.conn,
            campaign["id"],
            """name,email,phone,channel,department,manager
Imported Email,imported@example.test,,email,Finance,Avery
Imported SMS,,+1 (555) 010-3333,sms,Operations,Jordan
Existing Target,existing@example.test,,email,Finance,Avery
Broken Voice,,,voice,Support,Morgan
""",
            original_filename="targets.csv",
        )

        self.assertEqual(result["batch"]["status"], "completed_with_errors")
        self.assertEqual(result["batch"]["total_rows"], 4)
        self.assertEqual(result["batch"]["valid_rows"], 2)
        self.assertEqual(result["batch"]["invalid_rows"], 2)
        self.assertEqual(result["batch"]["imported_rows"], 2)
        self.assertEqual(len(result["targets"]), 2)
        self.assertTrue(any("already exists" in error["message"] for error in result["errors"]))
        self.assertTrue(any("phone number" in error["message"].lower() for error in result["errors"]))
        targets = list_targets(self.conn, campaign["id"])
        self.assertEqual(len(targets), 3)
        self.assertEqual(
            len([target for target in targets if target["source"] == "csv"]),
            2,
        )

    def test_archived_records_remain_available_in_metrics_and_history(self):
        campaign = create_campaign(self.conn, "Archived Metrics Test", selected_channels=["email"])
        target = create_target(
            self.conn,
            campaign["id"],
            name="Archived Target",
            email="archived.target@example.test",
            channel="email",
        )
        event = record_simulation_event(
            self.conn,
            campaign["id"],
            "link_click",
            target_id=target["id"],
            metadata={"source": "archive-coverage"},
        )

        archived_target = archive_target(self.conn, target["id"])
        archived_campaign = archive_campaign(self.conn, campaign["id"])

        metrics = get_campaign_metrics(self.conn, campaign["id"])
        detail = get_campaign_detail(self.conn, campaign["id"])
        events = list_simulation_events(self.conn, campaign["id"])

        self.assertTrue(archived_campaign["archived"])
        self.assertTrue(archived_target["archived"])
        self.assertEqual(metrics["aggregate"]["total_targets"], 1)
        self.assertEqual(metrics["aggregate"]["link_clicked"], 1)
        self.assertEqual(detail["campaign"]["id"], campaign["id"])
        self.assertEqual(detail["targets"][0]["id"], target["id"])
        self.assertTrue(detail["targets"][0]["archived"])
        self.assertEqual(events[0]["id"], event["id"])
        self.assertIn("archive-coverage", events[0]["metadata"])

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

    def test_records_delivery_orchestration_event_types(self):
        target_id = self.conn.execute(
            """
            SELECT id
            FROM simulation_targets
            WHERE campaign_id = ? AND channel = 'email'
            LIMIT 1
            """,
            (self.campaign_id,),
        ).fetchone()[0]

        queued = record_simulation_event(
            self.conn,
            self.campaign_id,
            "queued",
            target_id=target_id,
            metadata={"delivery_job_id": 1},
        )
        failed = record_simulation_event(
            self.conn,
            self.campaign_id,
            "failed",
            target_id=target_id,
            delivery_status="failed",
            metadata={"error_message": "provider unavailable", "retry_count": 2},
        )
        voice = record_simulation_event(
            self.conn,
            self.campaign_id,
            "voice_response",
            channel="voice",
            metadata={"response": "completed_training"},
        )

        self.assertEqual(queued["delivery_status"], "queued")
        self.assertEqual(failed["delivery_status"], "failed")
        self.assertEqual(voice["event_type"], "voice_response")
        self.assertIn("completed_training", voice["metadata"])

        delivery_status = self.conn.execute(
            """
            SELECT delivery_status
            FROM simulation_targets
            WHERE id = ?
            """,
            (target_id,),
        ).fetchone()[0]
        self.assertEqual(delivery_status, "failed")

    def test_campaign_detail_includes_ai_draft_history(self):
        provider = next(
            provider
            for provider in list_ai_provider_settings(self.conn)
            if provider["provider_type"] == "local"
        )
        first = save_ai_campaign_draft(
            self.conn,
            self.campaign_id,
            {
                "email_subject": "Training simulation: invoice review",
                "email_body": "Authorized training simulation email draft.",
                "training_text": "Report suspicious invoice messages.",
            },
            ["email"],
            provider=provider,
            risk_flags=["authorized_training_label_present"],
            safety_notes=["Credential collection language was excluded."],
        )
        second = save_ai_campaign_draft(
            self.conn,
            self.campaign_id,
            {
                "sms_body": "Authorized training simulation SMS draft.",
                "voice_script": "Authorized security awareness training simulation voice script.",
            },
            ["sms", "voice"],
            provider=provider,
            risk_flags=["authorized_training_label_present"],
        )

        detail = get_campaign_detail(self.conn, self.campaign_id)

        self.assertEqual([draft["id"] for draft in detail["ai_drafts"]], [second["id"], first["id"]])
        self.assertEqual(detail["ai_drafts"][0]["channels"], ["sms", "voice"])
        self.assertIn("Authorized training simulation", detail["ai_drafts"][0]["sms_body"])
        self.assertEqual(detail["ai_drafts"][1]["email_subject"], "Training simulation: invoice review")

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

    def test_ai_generation_audit_persists_prompt_output_and_risk_flags_without_secrets(self):
        provider = next(
            provider
            for provider in list_ai_provider_settings(self.conn)
            if provider["provider_type"] == "local"
        )
        update_ai_provider_settings(
            self.conn,
            provider["id"],
            secret="never-store-this-secret-in-audit",
        )
        request = AIScenarioRequest(
            "Practice safe link review",
            "Engineering",
            ["email", "sms"],
            safety_constraints=["Use authorized training labels"],
        )

        response = generate_ai_scenario(self.conn, provider["id"], request)
        audits = list_ai_generation_audits(self.conn, provider_id=provider["id"])

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["status"], "generated")
        self.assertEqual(audits[0]["provider_type"], "local")
        self.assertEqual(audits[0]["request"]["scenario_goal"], "Practice safe link review")
        self.assertEqual(audits[0]["output"]["channels"], ["email", "sms"])
        self.assertIn("credential_collection_disallowed", audits[0]["risk_flags"])
        self.assertEqual(response.draft.metadata["artifact_label"], "authorized_security_awareness_training")
        self.assertNotIn("secret_placeholder", str(audits[0]))
        self.assertNotIn("never-store-this-secret-in-audit", str(audits[0]))

    def test_generated_risk_flags_persist_to_saved_draft_history(self):
        provider = next(
            provider
            for provider in list_ai_provider_settings(self.conn)
            if provider["provider_type"] == "local"
        )
        request = AIScenarioRequest(
            "Practice reporting suspicious voicemail and text requests",
            "Operations",
            ["sms", "voice"],
            training_reminder="Report suspicious requests through the approved workflow.",
        )

        response = generate_ai_scenario(self.conn, provider["id"], request)
        audit = list_ai_generation_audits(self.conn, provider_id=provider["id"])[0]
        saved = save_ai_campaign_draft(
            self.conn,
            self.campaign_id,
            {
                "sms_body": response.draft.sms_body,
                "voice_script": response.draft.voice_script,
                "landing_text": response.draft.landing_text,
                "training_text": response.draft.training_text,
            },
            response.channels,
            provider={
                "id": response.provider_id,
                "name": response.provider_name,
                "provider_type": response.provider_type,
                "model_name": response.model_name,
            },
            risk_flags=response.risk_flags,
            safety_notes=response.safety_notes,
            metadata=response.metadata,
            audit_id=audit["id"],
        )
        detail = get_campaign_detail(self.conn, self.campaign_id)

        self.assertEqual(saved["audit_id"], audit["id"])
        self.assertEqual(detail["ai_drafts"][0]["id"], saved["id"])
        self.assertEqual(detail["ai_drafts"][0]["channels"], ["sms", "voice"])
        self.assertIn("credential_collection_disallowed", detail["ai_drafts"][0]["risk_flags"])
        self.assertIn("real_brand_impersonation_omitted", detail["ai_drafts"][0]["risk_flags"])
        self.assertEqual(
            detail["ai_drafts"][0]["metadata"]["artifact_label"],
            "authorized_security_awareness_training",
        )

    def test_blocked_ai_generation_attempt_is_audited(self):
        provider = next(
            provider
            for provider in list_ai_provider_settings(self.conn)
            if provider["provider_type"] == "local"
        )
        request = AIScenarioRequest(
            "Harvest credentials from employees",
            "Finance",
            ["email"],
        )

        with self.assertRaises(AIContentPolicyError):
            generate_ai_scenario(self.conn, provider["id"], request)

        audits = list_ai_generation_audits(self.conn, provider_id=provider["id"], status="blocked")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["request"]["scenario_goal"], "Harvest credentials from employees")
        self.assertIsNone(audits[0]["output"])
        self.assertIn("credential_harvesting_request", audits[0]["risk_flags"])
        self.assertIn("blocked by safety guardrails", audits[0]["error_reason"])


if __name__ == "__main__":
    unittest.main()
