import importlib
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.db_migration import SIMULATION_DEMO_SLUG, migrate_db

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
    db_path = str(Path(temp_dir) / "socialfish-http-verification.db")
    migrate_db(db_path)

    with mock.patch.object(sys, "argv", ["SocialFish.py", "verify-user", "verify-pass"]):
        socialfish = importlib.import_module("SocialFish")

    socialfish.app.config["TESTING"] = True
    original_database = socialfish.DATABASE
    socialfish.DATABASE = db_path
    try:
        client = socialfish.app.test_client()
        login = client.post("/neptune", data={"email": "verify-user", "password": "verify-pass"})
        assert login.status_code in (302, 200), login.status_code

        with sqlite3.connect(db_path) as conn:
            campaign_id = conn.execute(
                "SELECT id FROM simulation_campaigns WHERE slug = ?",
                (SIMULATION_DEMO_SLUG,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE simulation_campaigns SET training_url = ? WHERE id = ?",
                ("https://training.example.test/verified", campaign_id),
            )
            conn.commit()

        preview_response = client.post(
            f"/simulations/campaigns/{campaign_id}/deliveries/preview",
            json={"mode": "dry_run"},
        )
        assert preview_response.status_code == 200, preview_response.data
        preview = preview_response.get_json()["preview"]
        assert preview["total_targets"] == 4, preview
        assert preview["total_attempts"] == 4, preview
        assert set(preview["providers"].keys()) == {"email", "sms", "voice"}, preview

        start_response = client.post(
            f"/simulations/campaigns/{campaign_id}/deliveries/start",
            json={"mode": "dry_run", "max_retries": 0},
        )
        assert start_response.status_code == 200, start_response.data
        delivery = start_response.get_json()["delivery"]
        job_id = delivery["job"]["id"]
        assert delivery["job"]["status"] == "completed", delivery["job"]
        assert delivery["job"]["delivered_count"] == 4, delivery["job"]
        assert len(delivery["attempts"]) == 4, delivery["attempts"]
        assert len(delivery["tracking_tokens"]) == 12, delivery["tracking_tokens"]

        job_response = client.get(f"/api/simulations/deliveries/{job_id}")
        assert job_response.status_code == 200, job_response.data
        job_payload = job_response.get_json()["delivery"]
        assert job_payload["job"]["id"] == job_id, job_payload["job"]
        assert job_payload["job"]["mode"] == "dry_run", job_payload["job"]

        with sqlite3.connect(db_path) as conn:
            target_flags = {
                row[0]: {"opened": row[1], "link_clicked": row[2], "attachment_opened": row[3]}
                for row in conn.execute(
                    """
                    SELECT id, opened, link_clicked, attachment_opened
                    FROM simulation_targets
                    WHERE campaign_id = ?
                    """,
                    (campaign_id,),
                ).fetchall()
            }

        open_token = next(
            token for token in delivery["tracking_tokens"]
            if token["token_type"] == "open" and not target_flags[token["target_id"]]["opened"]
        )
        link_token = next(
            token for token in delivery["tracking_tokens"]
            if token["token_type"] == "link" and not target_flags[token["target_id"]]["link_clicked"]
        )
        attachment_token = next(
            token for token in delivery["tracking_tokens"]
            if token["token_type"] == "attachment" and not target_flags[token["target_id"]]["attachment_opened"]
        )

        open_response = client.get(f"/simulations/track/open/{open_token['token']}")
        link_response = client.get(f"/simulations/track/link/{link_token['token']}")
        attachment_response = client.post(f"/simulations/track/attachment/{attachment_token['token']}")
        assert open_response.status_code == 200, open_response.status_code
        assert open_response.mimetype == "image/gif", open_response.mimetype
        assert link_response.status_code == 302, link_response.status_code
        assert link_response.headers["Location"] == "https://training.example.test/verified", link_response.headers.get("Location")
        assert attachment_response.status_code == 200, attachment_response.data
        assert attachment_response.get_json()["event"]["event_type"] == "attachment_open"

        metrics_response = client.get("/api/simulations/metrics")
        assert metrics_response.status_code == 200, metrics_response.data
        aggregate = metrics_response.get_json()["metrics"]["aggregate"]
        assert aggregate["delivered"] == 4, aggregate
        assert aggregate["opened"] == 4, aggregate
        assert aggregate["link_clicked"] == 3, aggregate
        assert aggregate["attachment_opened"] == 2, aggregate

        with sqlite3.connect(db_path) as conn:
            token_count = conn.execute(
                """
                SELECT SUM(event_count)
                FROM simulation_tracking_tokens
                WHERE id IN (?, ?, ?)
                """,
                (open_token["id"], link_token["id"], attachment_token["id"]),
            ).fetchone()[0]
            event_types = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT event_type
                    FROM simulation_events
                    WHERE tracking_token_id IN (?, ?, ?)
                    ORDER BY id
                    """,
                    (open_token["id"], link_token["id"], attachment_token["id"]),
                ).fetchall()
            ]
        assert token_count == 3, token_count
        assert event_types == ["opened", "link_click", "attachment_open"], event_types
        print(
            "HTTP verification passed:",
            {
                "campaign_id": campaign_id,
                "job_id": job_id,
                "attempts": len(delivery["attempts"]),
                "tokens": len(delivery["tracking_tokens"]),
                "metrics": aggregate,
                "tracked_events": event_types,
            },
        )
    finally:
        socialfish.DATABASE = original_database
