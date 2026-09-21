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
                "simulation_targets",
                "simulation_events",
                "ai_provider_configs",
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

            conn.close()


if __name__ == "__main__":
    unittest.main()
