#!/usr/bin/env python3
"""
Database schema migration for SocialFish v3.0
Adds tables for Playwright recorder, templates, sessions, webhooks, cookies, and MITM config.
"""

import sqlite3
import os
from datetime import UTC, datetime


SIMULATION_DEMO_SLUG = "authorized-training-demo"


def _ensure_columns(cur, table_name, columns):
    """Add missing columns when an older prototype schema already exists."""
    existing = {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})")}
    for column_name, column_definition in columns.items():
        if column_name not in existing:
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _seed_simulation_demo(cur):
    """Seed deterministic authorized training data for the Simulation Center."""
    row = cur.execute(
        "SELECT id FROM simulation_campaigns WHERE slug = ?",
        (SIMULATION_DEMO_SLUG,),
    ).fetchone()
    if row:
        return

    now = datetime.now(UTC).isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO simulation_campaigns (
            slug, name, description, channel, status, authorized_scope,
            authorization_statement, started_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            SIMULATION_DEMO_SLUG,
            "Authorized Training Demo Campaign",
            "Seeded internal-only awareness simulation data for the Phase 01 dashboard.",
            "email",
            "active",
            "Authorized internal training simulation only; no external delivery is configured.",
            "I confirm this campaign is authorized for internal security awareness training by the Cybersecurity Team.",
            now,
            now,
            now,
        ),
    )
    campaign_id = cur.lastrowid

    targets = [
        {
            "name": "Avery Stone",
            "email": "avery.stone@example.test",
            "phone": "+15550101001",
            "department": "Finance",
            "channel": "email",
            "delivery_status": "delivered",
            "opened": 1,
            "forwarded": 0,
            "deleted": 0,
            "link_clicked": 1,
            "attachment_opened": 0,
        },
        {
            "name": "Jordan Lee",
            "email": "jordan.lee@example.test",
            "phone": "+15550101002",
            "department": "Operations",
            "channel": "sms",
            "delivery_status": "delivered",
            "opened": 1,
            "forwarded": 1,
            "deleted": 0,
            "link_clicked": 1,
            "attachment_opened": 0,
        },
        {
            "name": "Morgan Patel",
            "email": "morgan.patel@example.test",
            "phone": "+15550101003",
            "department": "Support",
            "channel": "voice",
            "delivery_status": "delivered",
            "opened": 0,
            "forwarded": 0,
            "deleted": 1,
            "link_clicked": 0,
            "attachment_opened": 0,
        },
        {
            "name": "Riley Chen",
            "email": "riley.chen@example.test",
            "phone": "+15550101004",
            "department": "Engineering",
            "channel": "email",
            "delivery_status": "delivered",
            "opened": 1,
            "forwarded": 0,
            "deleted": 0,
            "link_clicked": 0,
            "attachment_opened": 1,
        },
    ]

    event_map = [
        ("delivered", "delivered_at"),
        ("opened", "opened_at"),
        ("forwarded", "forwarded_at"),
        ("deleted", "deleted_at"),
        ("link_clicked", "link_clicked_at"),
        ("attachment_opened", "attachment_opened_at"),
    ]

    for target in targets:
        timestamps = {
            "delivered_at": now if target["delivery_status"] == "delivered" else None,
            "opened_at": now if target["opened"] else None,
            "forwarded_at": now if target["forwarded"] else None,
            "deleted_at": now if target["deleted"] else None,
            "link_clicked_at": now if target["link_clicked"] else None,
            "attachment_opened_at": now if target["attachment_opened"] else None,
        }
        cur.execute(
            """
            INSERT INTO simulation_targets (
                campaign_id, name, email, phone, department, channel,
                delivery_status, opened, forwarded, deleted, link_clicked,
                attachment_opened, delivered_at, opened_at, forwarded_at,
                deleted_at, link_clicked_at, attachment_opened_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                target["name"],
                target["email"],
                target["phone"],
                target["department"],
                target["channel"],
                target["delivery_status"],
                target["opened"],
                target["forwarded"],
                target["deleted"],
                target["link_clicked"],
                target["attachment_opened"],
                timestamps["delivered_at"],
                timestamps["opened_at"],
                timestamps["forwarded_at"],
                timestamps["deleted_at"],
                timestamps["link_clicked_at"],
                timestamps["attachment_opened_at"],
                now,
                now,
            ),
        )
        target_id = cur.lastrowid

        for event_type, timestamp_key in event_map:
            if event_type == "delivered" or target.get(event_type):
                cur.execute(
                    """
                    INSERT INTO simulation_events (
                        campaign_id, target_id, channel, event_type,
                        delivery_status, occurred_at, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        target_id,
                        target["channel"],
                        event_type,
                        target["delivery_status"],
                        timestamps[timestamp_key] or now,
                        '{"source":"seed","authorized_training":true}',
                    ),
                )

    provider_rows = [
        (
            "Local Demo Provider",
            "local",
            "local-simulation-model",
            "http://localhost:11434",
            1,
            "Seeded local provider placeholder; no API key required.",
        ),
        (
            "Cloud Demo Provider",
            "cloud",
            "cloud-awareness-model",
            "https://api.example.test/v1",
            0,
            "Seeded cloud provider placeholder; configure credentials in the UI later.",
        ),
    ]
    for name, provider_type, model_name, base_url, enabled, description in provider_rows:
        cur.execute(
            """
            INSERT INTO ai_provider_configs (
                name, provider_type, model_name, base_url, enabled,
                secret_placeholder, description, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                provider_type,
                model_name,
                base_url,
                enabled,
                "not-configured",
                description,
                now,
                now,
            ),
        )


def _seed_simulation_channel_providers(cur):
    """Seed safe provider references for delivery orchestration."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    provider_rows = [
        ("email", "dry_run_email", "Dry-run Email", "dry_run", 1, "[]"),
        ("sms", "dry_run_sms", "Dry-run SMS", "dry_run", 1, "[]"),
        ("voice", "dry_run_voice", "Dry-run Voice", "dry_run", 1, "[]"),
        ("email", "smtp_email", "SMTP Email", "smtp", 0, '["smtp_host","smtp_port","from_email"]'),
        ("email", "email_api", "Email API", "email_api", 0, '["api_key","from_email"]'),
        ("sms", "sms_api", "SMS API", "sms_api", 0, '["api_key","sender_id"]'),
        ("voice", "voice_api", "Voice API", "voice_api", 0, '["api_key","caller_id"]'),
    ]
    for channel, key, name, provider_type, enabled, required_settings in provider_rows:
        cur.execute(
            """
            INSERT OR IGNORE INTO simulation_channel_providers (
                channel, provider_key, provider_name, provider_type, enabled,
                settings_json, required_settings_json, secret_placeholder,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, '{}', ?, 'not-configured', ?, ?)
            """,
            (
                channel,
                key,
                name,
                provider_type,
                enabled,
                required_settings,
                now,
                now,
            ),
        )


def migrate_db(database_path):
    """Initialize or migrate database to latest schema"""
    
    conn = sqlite3.connect(database_path)
    cur = conn.cursor()
    
    # Enable foreign keys
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    
    # ============= LEGACY TABLES (keep existing) =============
    
    # Original creds table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS creds (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            jdoc TEXT,
            pdate NUMERIC,
            browser TEXT,
            bversion TEXT,
            platform TEXT,
            rip TEXT
        )
    """)
    
    # Original socialfish table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS socialfish (
            id INTEGER PRIMARY KEY,
            clicks INTEGER DEFAULT 0,
            attacks INTEGER DEFAULT 0,
            token TEXT
        )
    """)
    
    # Original sfmail table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sfmail (
            id INTEGER PRIMARY KEY,
            email VARCHAR,
            smtp TEXT,
            port TEXT
        )
    """)

    # Config table - stores site mode and clone URL settings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY,
            url TEXT,
            status TEXT,
            beef TEXT
        )
    """)
    
    # Original professionals table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS professionals (
            id INTEGER PRIMARY KEY,
            email VARCHAR,
            name TEXT,
            obs TEXT
        )
    """)
    
    # Original companies table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY,
            email VARCHAR,
            name TEXT,
            phone TEXT,
            address TEXT,
            site TEXT
        )
    """)
    
    # ============= NEW TABLES (v3.0+) =============
    
    # Templates - saved cloning configurations
    cur.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            base_url TEXT NOT NULL,
            description TEXT,
            tags TEXT,
            clone_mode TEXT DEFAULT 'both',
            browser_engine TEXT DEFAULT 'playwright',
            headless BOOLEAN DEFAULT 1,
            stealth BOOLEAN DEFAULT 1,
            form_selectors TEXT,
            csrf_token_selectors TEXT,
            auth_endpoints TEXT,
            captured_fields TEXT,
            wait_for_otp BOOLEAN DEFAULT 0,
            otp_input_selector TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    """)
    
    # Sessions - victim interactions and credential captures
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            template_id INTEGER,
            session_hash TEXT UNIQUE,
            victim_ip TEXT,
            victim_ua TEXT,
            victim_browser TEXT,
            victim_os TEXT,
            victim_device TEXT,
            victim_platform TEXT,
            victim_geoip TEXT,
            submission_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            form_data TEXT,
            submitted_credentials TEXT,
            session_state TEXT DEFAULT 'created',
            screenshot_path TEXT,
            notes TEXT,
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    """)
    
    # Cookies - detailed cookie capture per session
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cookies (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            name TEXT,
            value TEXT,
            domain TEXT,
            path TEXT,
            secure BOOLEAN,
            httponly BOOLEAN,
            samesite TEXT,
            expires TIMESTAMP,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # Network logs - HTTP requests/responses during recording/replay
    cur.execute("""
        CREATE TABLE IF NOT EXISTS network_logs (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            request_method TEXT,
            request_url TEXT,
            request_headers TEXT,
            request_body TEXT,
            response_status INTEGER,
            response_headers TEXT,
            response_body TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # Screenshots - captured during user interactions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            file_path TEXT,
            step_name TEXT,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # MITM configuration - reverse proxy and tunneling setup
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mitm_config (
            id INTEGER PRIMARY KEY,
            template_id INTEGER,
            tunnel_type TEXT DEFAULT 'none',
            tunnel_token TEXT,
            tunnel_domain TEXT,
            local_port INTEGER DEFAULT 5000,
            loopback_address TEXT DEFAULT 'localhost',
            lure_url TEXT,
            reverse_proxy_enabled BOOLEAN DEFAULT 0,
            intercept_network BOOLEAN DEFAULT 1,
            intercept_cookies BOOLEAN DEFAULT 1,
            redirect_after_capture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    """)
    
    # Webhooks - notification endpoints for victim interactions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY,
            template_id INTEGER,
            webhook_url TEXT NOT NULL,
            webhook_type TEXT DEFAULT 'json',
            trigger_on TEXT,
            payload_template TEXT,
            enabled BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    """)
    
    # Webhook logs - track webhook delivery
    cur.execute("""
        CREATE TABLE IF NOT EXISTS webhook_logs (
            id INTEGER PRIMARY KEY,
            webhook_id INTEGER,
            session_id INTEGER,
            payload TEXT,
            response_status INTEGER,
            response_body TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (webhook_id) REFERENCES webhooks(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # Lure URLs - tracking generated phishing links
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lure_urls (
            id INTEGER PRIMARY KEY,
            template_id INTEGER,
            lure_hash TEXT UNIQUE,
            full_url TEXT,
            short_url TEXT,
            click_count INTEGER DEFAULT 0,
            first_click TIMESTAMP,
            last_click TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    """)
    
    # Analyzer logs - multi-step, 2FA, and flow detection
    cur.execute("""
        CREATE TABLE IF NOT EXISTS analyzer_logs (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            detection_type TEXT,
            detection_value TEXT,
            confidence REAL,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    
    # Tunnel management - active tunnel sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tunnel_sessions (
            id INTEGER PRIMARY KEY,
            template_id INTEGER,
            tunnel_type TEXT,
            tunnel_pid INTEGER,
            tunnel_url TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id)
        )
    """)

    # ============= SIMULATION CENTER PROTOTYPE (Phase 01) =============

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_campaigns (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            objective TEXT,
            training_owner TEXT,
            channel TEXT NOT NULL DEFAULT 'email',
            selected_channels TEXT NOT NULL DEFAULT '["email"]',
            status TEXT NOT NULL DEFAULT 'draft',
            authorized_scope TEXT,
            authorization_statement TEXT,
            landing_url TEXT,
            training_url TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            archived_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _ensure_columns(cur, "simulation_campaigns", {
        "slug": "TEXT",
        "name": "TEXT",
        "description": "TEXT",
        "objective": "TEXT",
        "training_owner": "TEXT",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "selected_channels": "TEXT NOT NULL DEFAULT '[\"email\"]'",
        "status": "TEXT NOT NULL DEFAULT 'draft'",
        "authorized_scope": "TEXT",
        "authorization_statement": "TEXT",
        "landing_url": "TEXT",
        "training_url": "TEXT",
        "start_date": "TIMESTAMP",
        "end_date": "TIMESTAMP",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "archived_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })
    cur.execute(
        """
        UPDATE simulation_campaigns
        SET authorization_statement = ?
        WHERE slug = ?
          AND (authorization_statement IS NULL OR TRIM(authorization_statement) = '')
        """,
        (
            "I confirm this campaign is authorized for internal security awareness training by the Cybersecurity Team.",
            SIMULATION_DEMO_SLUG,
        ),
    )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_import_batches (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            original_filename TEXT,
            stored_filename TEXT,
            source TEXT NOT NULL DEFAULT 'csv',
            status TEXT NOT NULL DEFAULT 'pending',
            total_rows INTEGER NOT NULL DEFAULT 0,
            valid_rows INTEGER NOT NULL DEFAULT 0,
            invalid_rows INTEGER NOT NULL DEFAULT 0,
            imported_rows INTEGER NOT NULL DEFAULT 0,
            validation_errors TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id)
        )
    """)
    _ensure_columns(cur, "simulation_import_batches", {
        "campaign_id": "INTEGER",
        "original_filename": "TEXT",
        "stored_filename": "TEXT",
        "source": "TEXT NOT NULL DEFAULT 'csv'",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "total_rows": "INTEGER NOT NULL DEFAULT 0",
        "valid_rows": "INTEGER NOT NULL DEFAULT 0",
        "invalid_rows": "INTEGER NOT NULL DEFAULT 0",
        "imported_rows": "INTEGER NOT NULL DEFAULT 0",
        "validation_errors": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "completed_at": "TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_targets (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            display_name TEXT,
            email TEXT,
            phone TEXT,
            department TEXT,
            manager TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            source_reference TEXT,
            source_metadata_json TEXT NOT NULL DEFAULT '{}',
            active BOOLEAN NOT NULL DEFAULT 1,
            import_batch_id INTEGER,
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
            archived_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (import_batch_id) REFERENCES simulation_import_batches(id)
        )
    """)
    _ensure_columns(cur, "simulation_targets", {
        "campaign_id": "INTEGER",
        "name": "TEXT",
        "display_name": "TEXT",
        "email": "TEXT",
        "phone": "TEXT",
        "department": "TEXT",
        "manager": "TEXT",
        "source": "TEXT NOT NULL DEFAULT 'manual'",
        "source_reference": "TEXT",
        "source_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "active": "BOOLEAN NOT NULL DEFAULT 1",
        "import_batch_id": "INTEGER",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "delivery_status": "TEXT NOT NULL DEFAULT 'pending'",
        "opened": "BOOLEAN NOT NULL DEFAULT 0",
        "forwarded": "BOOLEAN NOT NULL DEFAULT 0",
        "deleted": "BOOLEAN NOT NULL DEFAULT 0",
        "link_clicked": "BOOLEAN NOT NULL DEFAULT 0",
        "attachment_opened": "BOOLEAN NOT NULL DEFAULT 0",
        "delivered_at": "TIMESTAMP",
        "opened_at": "TIMESTAMP",
        "forwarded_at": "TIMESTAMP",
        "deleted_at": "TIMESTAMP",
        "link_clicked_at": "TIMESTAMP",
        "attachment_opened_at": "TIMESTAMP",
        "archived_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_events (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            target_id INTEGER,
            channel TEXT NOT NULL,
            event_type TEXT NOT NULL,
            delivery_status TEXT,
            occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (target_id) REFERENCES simulation_targets(id)
        )
    """)
    _ensure_columns(cur, "simulation_events", {
        "campaign_id": "INTEGER",
        "target_id": "INTEGER",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "event_type": "TEXT",
        "delivery_status": "TEXT",
        "delivery_job_id": "INTEGER",
        "delivery_attempt_id": "INTEGER",
        "tracking_token_id": "INTEGER",
        "provider_reference_id": "INTEGER",
        "provider": "TEXT",
        "provider_event_id": "TEXT",
        "error_message": "TEXT",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "occurred_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "metadata": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    # ============= SIMULATION DELIVERY ORCHESTRATION (Phase 04) =============

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_channel_providers (
            id INTEGER PRIMARY KEY,
            channel TEXT NOT NULL,
            provider_key TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            provider_type TEXT NOT NULL DEFAULT 'dry_run',
            enabled BOOLEAN NOT NULL DEFAULT 0,
            settings_json TEXT,
            required_settings_json TEXT,
            secret_placeholder TEXT,
            last_error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel, provider_key)
        )
    """)
    _ensure_columns(cur, "simulation_channel_providers", {
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "provider_key": "TEXT",
        "provider_name": "TEXT",
        "provider_type": "TEXT NOT NULL DEFAULT 'dry_run'",
        "enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "settings_json": "TEXT",
        "required_settings_json": "TEXT",
        "secret_placeholder": "TEXT",
        "last_error_message": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_delivery_jobs (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            mode TEXT NOT NULL DEFAULT 'dry_run',
            requested_by TEXT,
            provider_snapshot TEXT,
            total_targets INTEGER NOT NULL DEFAULT 0,
            total_attempts INTEGER NOT NULL DEFAULT 0,
            queued_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            delivered_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id)
        )
    """)
    _ensure_columns(cur, "simulation_delivery_jobs", {
        "campaign_id": "INTEGER",
        "status": "TEXT NOT NULL DEFAULT 'queued'",
        "mode": "TEXT NOT NULL DEFAULT 'dry_run'",
        "requested_by": "TEXT",
        "provider_snapshot": "TEXT",
        "total_targets": "INTEGER NOT NULL DEFAULT 0",
        "total_attempts": "INTEGER NOT NULL DEFAULT 0",
        "queued_count": "INTEGER NOT NULL DEFAULT 0",
        "sent_count": "INTEGER NOT NULL DEFAULT 0",
        "delivered_count": "INTEGER NOT NULL DEFAULT 0",
        "failed_count": "INTEGER NOT NULL DEFAULT 0",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "error_message": "TEXT",
        "queued_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_message_artifacts (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            delivery_job_id INTEGER,
            channel TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            content_json TEXT,
            content_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (delivery_job_id) REFERENCES simulation_delivery_jobs(id)
        )
    """)
    _ensure_columns(cur, "simulation_message_artifacts", {
        "campaign_id": "INTEGER",
        "delivery_job_id": "INTEGER",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "artifact_type": "TEXT NOT NULL DEFAULT 'message'",
        "subject": "TEXT",
        "body": "TEXT",
        "content_json": "TEXT",
        "content_hash": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_tracking_tokens (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            delivery_job_id INTEGER,
            message_artifact_id INTEGER,
            channel TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            token_type TEXT NOT NULL,
            destination_url TEXT,
            expires_at TIMESTAMP,
            first_seen_at TIMESTAMP,
            last_seen_at TIMESTAMP,
            event_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (target_id) REFERENCES simulation_targets(id),
            FOREIGN KEY (delivery_job_id) REFERENCES simulation_delivery_jobs(id),
            FOREIGN KEY (message_artifact_id) REFERENCES simulation_message_artifacts(id)
        )
    """)
    _ensure_columns(cur, "simulation_tracking_tokens", {
        "campaign_id": "INTEGER",
        "target_id": "INTEGER",
        "delivery_job_id": "INTEGER",
        "message_artifact_id": "INTEGER",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "token": "TEXT",
        "token_type": "TEXT NOT NULL DEFAULT 'open'",
        "destination_url": "TEXT",
        "expires_at": "TIMESTAMP",
        "first_seen_at": "TIMESTAMP",
        "last_seen_at": "TIMESTAMP",
        "event_count": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_delivery_attempts (
            id INTEGER PRIMARY KEY,
            delivery_job_id INTEGER NOT NULL,
            campaign_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            message_artifact_id INTEGER,
            provider_id INTEGER,
            channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            provider TEXT,
            provider_message_id TEXT,
            provider_response TEXT,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 0,
            queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            delivered_at TIMESTAMP,
            failed_at TIMESTAMP,
            next_retry_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (delivery_job_id) REFERENCES simulation_delivery_jobs(id),
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (target_id) REFERENCES simulation_targets(id),
            FOREIGN KEY (message_artifact_id) REFERENCES simulation_message_artifacts(id),
            FOREIGN KEY (provider_id) REFERENCES simulation_channel_providers(id),
            UNIQUE(delivery_job_id, target_id, channel)
        )
    """)
    _ensure_columns(cur, "simulation_delivery_attempts", {
        "delivery_job_id": "INTEGER",
        "campaign_id": "INTEGER",
        "target_id": "INTEGER",
        "message_artifact_id": "INTEGER",
        "provider_id": "INTEGER",
        "channel": "TEXT NOT NULL DEFAULT 'email'",
        "status": "TEXT NOT NULL DEFAULT 'queued'",
        "provider": "TEXT",
        "provider_message_id": "TEXT",
        "provider_response": "TEXT",
        "error_message": "TEXT",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "max_retries": "INTEGER NOT NULL DEFAULT 0",
        "queued_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "sent_at": "TIMESTAMP",
        "delivered_at": "TIMESTAMP",
        "failed_at": "TIMESTAMP",
        "next_retry_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_jobs_campaign ON simulation_delivery_jobs(campaign_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_attempts_job ON simulation_delivery_attempts(delivery_job_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_attempts_target ON simulation_delivery_attempts(target_id, channel, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tracking_tokens_token ON simulation_tracking_tokens(token)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tracking_tokens_target ON simulation_tracking_tokens(target_id, token_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_message_artifacts_job ON simulation_message_artifacts(delivery_job_id, channel)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_simulation_events_delivery_job ON simulation_events(delivery_job_id, delivery_attempt_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_provider_configs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            provider_type TEXT NOT NULL,
            model_name TEXT NOT NULL,
            base_url TEXT,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            secret_placeholder TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _ensure_columns(cur, "ai_provider_configs", {
        "name": "TEXT",
        "provider_type": "TEXT NOT NULL DEFAULT 'local'",
        "model_name": "TEXT",
        "base_url": "TEXT",
        "enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "secret_placeholder": "TEXT",
        "description": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_generation_audits (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER,
            provider_name TEXT,
            provider_type TEXT,
            model_name TEXT,
            request_json TEXT NOT NULL,
            output_json TEXT,
            risk_flags TEXT,
            safety_notes TEXT,
            metadata TEXT,
            status TEXT NOT NULL,
            error_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES ai_provider_configs(id)
        )
    """)
    _ensure_columns(cur, "ai_generation_audits", {
        "provider_id": "INTEGER",
        "provider_name": "TEXT",
        "provider_type": "TEXT",
        "model_name": "TEXT",
        "request_json": "TEXT",
        "output_json": "TEXT",
        "risk_flags": "TEXT",
        "safety_notes": "TEXT",
        "metadata": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'generated'",
        "error_reason": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    # ============= DIRECTORY INTEGRATION READINESS (Phase 06) =============

    cur.execute("""
        CREATE TABLE IF NOT EXISTS directory_providers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            provider_type TEXT NOT NULL DEFAULT 'mock_entra',
            tenant_id TEXT,
            tenant_name TEXT,
            authority_url TEXT,
            client_id TEXT,
            enabled BOOLEAN NOT NULL DEFAULT 0,
            consent_status TEXT NOT NULL DEFAULT 'not_configured',
            consented_scopes_json TEXT NOT NULL DEFAULT '[]',
            selected_groups_json TEXT NOT NULL DEFAULT '[]',
            field_mapping_json TEXT NOT NULL DEFAULT '{}',
            settings_json TEXT NOT NULL DEFAULT '{}',
            secret_reference TEXT,
            secret_placeholder TEXT,
            last_sync_status TEXT,
            last_sync_job_id INTEGER,
            last_sync_at TIMESTAMP,
            last_error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (last_sync_job_id) REFERENCES directory_sync_jobs(id)
        )
    """)
    _ensure_columns(cur, "directory_providers", {
        "name": "TEXT",
        "provider_type": "TEXT NOT NULL DEFAULT 'mock_entra'",
        "tenant_id": "TEXT",
        "tenant_name": "TEXT",
        "authority_url": "TEXT",
        "client_id": "TEXT",
        "enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "consent_status": "TEXT NOT NULL DEFAULT 'not_configured'",
        "consented_scopes_json": "TEXT NOT NULL DEFAULT '[]'",
        "selected_groups_json": "TEXT NOT NULL DEFAULT '[]'",
        "field_mapping_json": "TEXT NOT NULL DEFAULT '{}'",
        "settings_json": "TEXT NOT NULL DEFAULT '{}'",
        "secret_reference": "TEXT",
        "secret_placeholder": "TEXT",
        "last_sync_status": "TEXT",
        "last_sync_job_id": "INTEGER",
        "last_sync_at": "TIMESTAMP",
        "last_error_message": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS directory_sync_jobs (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'preview',
            status TEXT NOT NULL DEFAULT 'pending',
            selected_groups_json TEXT NOT NULL DEFAULT '[]',
            total_groups INTEGER NOT NULL DEFAULT 0,
            total_users INTEGER NOT NULL DEFAULT 0,
            staged_count INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            invalid_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            validation_errors_json TEXT NOT NULL DEFAULT '[]',
            requested_by TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES directory_providers(id)
        )
    """)
    _ensure_columns(cur, "directory_sync_jobs", {
        "provider_id": "INTEGER",
        "job_type": "TEXT NOT NULL DEFAULT 'preview'",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "selected_groups_json": "TEXT NOT NULL DEFAULT '[]'",
        "total_groups": "INTEGER NOT NULL DEFAULT 0",
        "total_users": "INTEGER NOT NULL DEFAULT 0",
        "staged_count": "INTEGER NOT NULL DEFAULT 0",
        "imported_count": "INTEGER NOT NULL DEFAULT 0",
        "skipped_count": "INTEGER NOT NULL DEFAULT 0",
        "invalid_count": "INTEGER NOT NULL DEFAULT 0",
        "duplicate_count": "INTEGER NOT NULL DEFAULT 0",
        "validation_errors_json": "TEXT NOT NULL DEFAULT '[]'",
        "requested_by": "TEXT",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staged_directory_users (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER NOT NULL,
            sync_job_id INTEGER NOT NULL,
            external_user_id TEXT NOT NULL,
            user_principal_name TEXT,
            mail TEXT,
            display_name TEXT,
            given_name TEXT,
            surname TEXT,
            job_title TEXT,
            department TEXT,
            office_location TEXT,
            mobile_phone TEXT,
            business_phones_json TEXT NOT NULL DEFAULT '[]',
            manager TEXT,
            groups_json TEXT NOT NULL DEFAULT '[]',
            source_group_ids_json TEXT NOT NULL DEFAULT '[]',
            active BOOLEAN NOT NULL DEFAULT 1,
            validation_status TEXT NOT NULL DEFAULT 'pending',
            validation_errors_json TEXT NOT NULL DEFAULT '[]',
            target_payload_json TEXT NOT NULL DEFAULT '{}',
            imported_target_id INTEGER,
            staged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            imported_at TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES directory_providers(id),
            FOREIGN KEY (sync_job_id) REFERENCES directory_sync_jobs(id),
            FOREIGN KEY (imported_target_id) REFERENCES simulation_targets(id),
            UNIQUE(provider_id, external_user_id)
        )
    """)
    _ensure_columns(cur, "staged_directory_users", {
        "provider_id": "INTEGER",
        "sync_job_id": "INTEGER",
        "external_user_id": "TEXT",
        "user_principal_name": "TEXT",
        "mail": "TEXT",
        "display_name": "TEXT",
        "given_name": "TEXT",
        "surname": "TEXT",
        "job_title": "TEXT",
        "department": "TEXT",
        "office_location": "TEXT",
        "mobile_phone": "TEXT",
        "business_phones_json": "TEXT NOT NULL DEFAULT '[]'",
        "manager": "TEXT",
        "groups_json": "TEXT NOT NULL DEFAULT '[]'",
        "source_group_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "active": "BOOLEAN NOT NULL DEFAULT 1",
        "validation_status": "TEXT NOT NULL DEFAULT 'pending'",
        "validation_errors_json": "TEXT NOT NULL DEFAULT '[]'",
        "target_payload_json": "TEXT NOT NULL DEFAULT '{}'",
        "imported_target_id": "INTEGER",
        "staged_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "imported_at": "TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS directory_group_mappings (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER NOT NULL,
            external_group_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            description TEXT,
            selected BOOLEAN NOT NULL DEFAULT 0,
            target_department TEXT,
            campaign_id INTEGER,
            mapping_metadata_json TEXT NOT NULL DEFAULT '{}',
            last_seen_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES directory_providers(id),
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            UNIQUE(provider_id, external_group_id)
        )
    """)
    _ensure_columns(cur, "directory_group_mappings", {
        "provider_id": "INTEGER",
        "external_group_id": "TEXT",
        "display_name": "TEXT",
        "description": "TEXT",
        "selected": "BOOLEAN NOT NULL DEFAULT 0",
        "target_department": "TEXT",
        "campaign_id": "INTEGER",
        "mapping_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "last_seen_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("""
        CREATE TABLE IF NOT EXISTS directory_sync_audit_events (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER,
            sync_job_id INTEGER,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            actor TEXT,
            message TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES directory_providers(id),
            FOREIGN KEY (sync_job_id) REFERENCES directory_sync_jobs(id)
        )
    """)
    _ensure_columns(cur, "directory_sync_audit_events", {
        "provider_id": "INTEGER",
        "sync_job_id": "INTEGER",
        "event_type": "TEXT",
        "severity": "TEXT NOT NULL DEFAULT 'info'",
        "actor": "TEXT",
        "message": "TEXT",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    cur.execute("CREATE INDEX IF NOT EXISTS idx_directory_providers_type ON directory_providers(provider_type, enabled)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_directory_sync_jobs_provider ON directory_sync_jobs(provider_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_staged_directory_users_job ON staged_directory_users(sync_job_id, validation_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_staged_directory_users_contact ON staged_directory_users(mail, user_principal_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_directory_group_mappings_provider ON directory_group_mappings(provider_id, selected)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_directory_sync_audit_events_job ON directory_sync_audit_events(sync_job_id, event_type)")

    # ============= ADMINISTRATIVE AUDIT EVENTS (Phase 07) =============

    cur.execute("""
        CREATE TABLE IF NOT EXISTS administrative_audit_events (
            id INTEGER PRIMARY KEY,
            actor_identity TEXT,
            action_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            campaign_id INTEGER,
            channel TEXT,
            ip_address TEXT,
            user_agent TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id)
        )
    """)
    _ensure_columns(cur, "administrative_audit_events", {
        "actor_identity": "TEXT",
        "action_type": "TEXT",
        "entity_type": "TEXT",
        "entity_id": "TEXT",
        "campaign_id": "INTEGER",
        "channel": "TEXT",
        "ip_address": "TEXT",
        "user_agent": "TEXT",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON administrative_audit_events(action_type, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_entity ON administrative_audit_events(entity_type, entity_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_campaign ON administrative_audit_events(campaign_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON administrative_audit_events(actor_identity, created_at)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_campaign_drafts (
            id INTEGER PRIMARY KEY,
            campaign_id INTEGER NOT NULL,
            audit_id INTEGER,
            provider_id INTEGER,
            provider_name TEXT,
            provider_type TEXT,
            model_name TEXT,
            channels TEXT NOT NULL,
            email_subject TEXT,
            email_body TEXT,
            sms_body TEXT,
            voice_script TEXT,
            landing_text TEXT,
            training_text TEXT,
            risk_flags TEXT,
            safety_notes TEXT,
            metadata TEXT,
            status TEXT NOT NULL DEFAULT 'approved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (campaign_id) REFERENCES simulation_campaigns(id),
            FOREIGN KEY (audit_id) REFERENCES ai_generation_audits(id),
            FOREIGN KEY (provider_id) REFERENCES ai_provider_configs(id)
        )
    """)
    _ensure_columns(cur, "ai_campaign_drafts", {
        "campaign_id": "INTEGER",
        "audit_id": "INTEGER",
        "provider_id": "INTEGER",
        "provider_name": "TEXT",
        "provider_type": "TEXT",
        "model_name": "TEXT",
        "channels": "TEXT NOT NULL DEFAULT '[]'",
        "email_subject": "TEXT",
        "email_body": "TEXT",
        "sms_body": "TEXT",
        "voice_script": "TEXT",
        "landing_text": "TEXT",
        "training_text": "TEXT",
        "risk_flags": "TEXT",
        "safety_notes": "TEXT",
        "metadata": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'approved'",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    })

    _seed_simulation_channel_providers(cur)
    _seed_simulation_demo(cur)
    
    conn.commit()
    conn.close()
    print(f"[+] Database migrated successfully: {database_path}")

if __name__ == "__main__":
    db_path = os.getenv("DATABASE", "./database.db")
    migrate_db(db_path)
