import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db


class SimulationMigrationTest(unittest.TestCase):
    def test_simulation_schema_and_seed_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "socialfish-test.db")

            migrate_db(db_path)
            migrate_db(db_path)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            expected_tables = {
                "simulation_campaigns",
                "simulation_import_batches",
                "simulation_targets",
                "simulation_events",
                "simulation_channel_providers",
                "simulation_delivery_jobs",
                "simulation_delivery_attempts",
                "simulation_message_artifacts",
                "simulation_tracking_tokens",
                "ai_provider_configs",
                "ai_generation_audits",
            }
            tables = {
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue(expected_tables.issubset(tables))

            campaign_count = cur.execute(
                "SELECT COUNT(*) FROM simulation_campaigns WHERE slug = ?",
                (SIMULATION_DEMO_SLUG,),
            ).fetchone()[0]
            self.assertEqual(campaign_count, 1)

            channels = {
                row[0]
                for row in cur.execute(
                    """
                    SELECT DISTINCT channel
                    FROM simulation_targets
                    WHERE campaign_id = (
                        SELECT id FROM simulation_campaigns WHERE slug = ?
                    )
                    """,
                    (SIMULATION_DEMO_SLUG,),
                )
            }
            self.assertEqual(channels, {"email", "sms", "voice"})

            metric_row = cur.execute(
                """
                SELECT
                    SUM(opened),
                    SUM(forwarded),
                    SUM(deleted),
                    SUM(link_clicked),
                    SUM(attachment_opened)
                FROM simulation_targets
                """
            ).fetchone()
            self.assertEqual(metric_row, (3, 1, 1, 2, 1))

            providers = {
                row[0]: row[1]
                for row in cur.execute(
                    "SELECT provider_type, enabled FROM ai_provider_configs"
                )
            }
            self.assertEqual(providers, {"local": 1, "cloud": 0})

            event_count = cur.execute(
                "SELECT COUNT(*) FROM simulation_events"
            ).fetchone()[0]
            self.assertGreaterEqual(event_count, 9)

            delivery_providers = {
                row[0]: row[1]
                for row in cur.execute(
                    """
                    SELECT provider_key, enabled
                    FROM simulation_channel_providers
                    """
                )
            }
            self.assertEqual(
                delivery_providers,
                {
                    "dry_run_email": 1,
                    "dry_run_sms": 1,
                    "dry_run_voice": 1,
                    "email_api": 0,
                    "sms_api": 0,
                    "smtp_email": 0,
                    "voice_api": 0,
                },
            )

            delivery_job_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_delivery_jobs)")
            }
            self.assertTrue(
                {
                    "campaign_id",
                    "status",
                    "mode",
                    "provider_snapshot",
                    "queued_count",
                    "sent_count",
                    "delivered_count",
                    "failed_count",
                    "retry_count",
                    "error_message",
                    "queued_at",
                    "started_at",
                    "completed_at",
                }.issubset(delivery_job_columns)
            )

            delivery_attempt_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_delivery_attempts)")
            }
            self.assertTrue(
                {
                    "delivery_job_id",
                    "campaign_id",
                    "target_id",
                    "message_artifact_id",
                    "provider_id",
                    "channel",
                    "status",
                    "provider",
                    "provider_message_id",
                    "provider_response",
                    "error_message",
                    "retry_count",
                    "queued_at",
                    "sent_at",
                    "delivered_at",
                    "failed_at",
                    "next_retry_at",
                }.issubset(delivery_attempt_columns)
            )

            tracking_token_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_tracking_tokens)")
            }
            self.assertTrue(
                {
                    "campaign_id",
                    "target_id",
                    "delivery_job_id",
                    "message_artifact_id",
                    "channel",
                    "token",
                    "token_type",
                    "destination_url",
                    "first_seen_at",
                    "last_seen_at",
                    "event_count",
                }.issubset(tracking_token_columns)
            )

            event_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_events)")
            }
            self.assertTrue(
                {
                    "delivery_job_id",
                    "delivery_attempt_id",
                    "tracking_token_id",
                    "provider_reference_id",
                    "provider",
                    "provider_event_id",
                    "error_message",
                    "retry_count",
                }.issubset(event_columns)
            )

            conn.close()

    def test_campaign_management_columns_are_added_to_existing_phase_01_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "socialfish-test.db")
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE simulation_campaigns (
                    id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT,
                    channel TEXT NOT NULL DEFAULT 'email',
                    status TEXT NOT NULL DEFAULT 'draft',
                    authorized_scope TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE simulation_targets (
                    id INTEGER PRIMARY KEY,
                    campaign_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    department TEXT,
                    channel TEXT NOT NULL,
                    delivery_status TEXT NOT NULL DEFAULT 'pending',
                    opened BOOLEAN NOT NULL DEFAULT 0,
                    forwarded BOOLEAN NOT NULL DEFAULT 0,
                    deleted BOOLEAN NOT NULL DEFAULT 0,
                    link_clicked BOOLEAN NOT NULL DEFAULT 0,
                    attachment_opened BOOLEAN NOT NULL DEFAULT 0,
                    delivered_at TIMESTAMP,
                    opened_at TIMESTAMP,
                    forwarded_at TIMESTAMP,
                    deleted_at TIMESTAMP,
                    link_clicked_at TIMESTAMP,
                    attachment_opened_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id)
                )
                """
            )
            conn.commit()
            conn.close()

            migrate_db(db_path)
            migrate_db(db_path)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            campaign_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_campaigns)")
            }
            self.assertTrue(
                {
                    "objective",
                    "training_owner",
                    "selected_channels",
                    "landing_url",
                    "training_url",
                    "start_date",
                    "end_date",
                    "archived_at",
                }.issubset(campaign_columns)
            )

            target_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_targets)")
            }
            self.assertTrue(
                {
                    "display_name",
                    "manager",
                    "source",
                    "active",
                    "import_batch_id",
                    "archived_at",
                }.issubset(target_columns)
            )

            import_batch_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_import_batches)")
            }
            self.assertTrue(
                {
                    "campaign_id",
                    "original_filename",
                    "stored_filename",
                    "source",
                    "status",
                    "total_rows",
                    "valid_rows",
                    "invalid_rows",
                    "imported_rows",
                    "validation_errors",
                    "created_at",
                    "updated_at",
                    "completed_at",
                }.issubset(import_batch_columns)
            )
            conn.close()

    def test_delivery_columns_are_added_to_existing_simulation_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "socialfish-test.db")
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE simulation_events (
                    id INTEGER PRIMARY KEY,
                    campaign_id INTEGER NOT NULL,
                    target_id INTEGER,
                    channel TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    delivery_status TEXT,
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            conn.close()

            migrate_db(db_path)
            migrate_db(db_path)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            event_columns = {
                row[1]
                for row in cur.execute("PRAGMA table_info(simulation_events)")
            }
            self.assertTrue(
                {
                    "delivery_job_id",
                    "delivery_attempt_id",
                    "tracking_token_id",
                    "provider_reference_id",
                    "provider",
                    "provider_event_id",
                    "error_message",
                    "retry_count",
                }.issubset(event_columns)
            )

            provider_count = cur.execute(
                "SELECT COUNT(*) FROM simulation_channel_providers"
            ).fetchone()[0]
            self.assertEqual(provider_count, 7)
            conn.close()


if __name__ == "__main__":
    unittest.main()
