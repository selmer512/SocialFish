from datetime import UTC, datetime
import json


VALID_SIMULATION_EVENTS = {
    "delivered": {
        "target_column": "delivery_status",
        "timestamp_column": "delivered_at",
        "status": "delivered",
    },
    "open": {
        "target_column": "opened",
        "timestamp_column": "opened_at",
    },
    "opened": {
        "target_column": "opened",
        "timestamp_column": "opened_at",
    },
    "forward": {
        "target_column": "forwarded",
        "timestamp_column": "forwarded_at",
    },
    "forwarded": {
        "target_column": "forwarded",
        "timestamp_column": "forwarded_at",
    },
    "delete": {
        "target_column": "deleted",
        "timestamp_column": "deleted_at",
    },
    "deleted": {
        "target_column": "deleted",
        "timestamp_column": "deleted_at",
    },
    "link_click": {
        "target_column": "link_clicked",
        "timestamp_column": "link_clicked_at",
    },
    "link_clicked": {
        "target_column": "link_clicked",
        "timestamp_column": "link_clicked_at",
    },
    "attachment_open": {
        "target_column": "attachment_opened",
        "timestamp_column": "attachment_opened_at",
    },
    "attachment_opened": {
        "target_column": "attachment_opened",
        "timestamp_column": "attachment_opened_at",
    },
}


def _utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows_to_dicts(cursor):
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _row_to_dict(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row))


def _bool(value):
    return bool(int(value or 0))


def _provider_response(row):
    provider = dict(row)
    provider["enabled"] = _bool(provider.get("enabled"))
    provider["secret_configured"] = provider.get("secret_placeholder") == "configured"
    provider.pop("secret_placeholder", None)
    return provider


def list_campaigns(conn):
    """Return simulation campaigns with target counts for dashboard summaries."""
    cursor = conn.execute(
        """
        SELECT
            c.id,
            c.slug,
            c.name,
            c.description,
            c.channel,
            c.status,
            c.authorized_scope,
            c.started_at,
            c.completed_at,
            c.created_at,
            c.updated_at,
            COUNT(t.id) AS target_count
        FROM simulation_campaigns c
        LEFT JOIN simulation_targets t ON t.campaign_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        """
    )
    return _rows_to_dicts(cursor)


def list_targets(conn, campaign_id=None):
    """Return targets for one campaign or all campaigns."""
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE t.campaign_id = ?"
        params.append(campaign_id)

    cursor = conn.execute(
        f"""
        SELECT
            t.id,
            t.campaign_id,
            c.name AS campaign_name,
            t.name,
            t.email,
            t.phone,
            t.department,
            t.channel,
            t.delivery_status,
            t.opened,
            t.forwarded,
            t.deleted,
            t.link_clicked,
            t.attachment_opened,
            t.delivered_at,
            t.opened_at,
            t.forwarded_at,
            t.deleted_at,
            t.link_clicked_at,
            t.attachment_opened_at,
            t.created_at,
            t.updated_at
        FROM simulation_targets t
        JOIN simulation_campaigns c ON c.id = t.campaign_id
        {where}
        ORDER BY t.id ASC
        """,
        params,
    )
    rows = _rows_to_dicts(cursor)
    for row in rows:
        for field in ("opened", "forwarded", "deleted", "link_clicked", "attachment_opened"):
            row[field] = _bool(row[field])
    return rows


def get_campaign_metrics(conn, campaign_id=None):
    """Calculate aggregate and channel-level simulation metrics."""
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE campaign_id = ?"
        params.append(campaign_id)

    aggregate = _row_to_dict(
        conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_targets,
                SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
                SUM(opened) AS opened,
                SUM(forwarded) AS forwarded,
                SUM(deleted) AS deleted,
                SUM(link_clicked) AS link_clicked,
                SUM(attachment_opened) AS attachment_opened
            FROM simulation_targets
            {where}
            """,
            params,
        )
    )
    if not aggregate:
        aggregate = {}

    metric_fields = (
        "total_targets",
        "delivered",
        "opened",
        "forwarded",
        "deleted",
        "link_clicked",
        "attachment_opened",
    )
    for field in metric_fields:
        aggregate[field] = int(aggregate.get(field) or 0)

    channel_rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                channel,
                COUNT(*) AS total_targets,
                SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
                SUM(opened) AS opened,
                SUM(forwarded) AS forwarded,
                SUM(deleted) AS deleted,
                SUM(link_clicked) AS link_clicked,
                SUM(attachment_opened) AS attachment_opened
            FROM simulation_targets
            {where}
            GROUP BY channel
            ORDER BY channel ASC
            """,
            params,
        )
    )
    by_channel = {}
    for row in channel_rows:
        channel = row.pop("channel")
        by_channel[channel] = {field: int(row.get(field) or 0) for field in metric_fields}

    return {
        "aggregate": aggregate,
        "channels": by_channel,
        "campaigns": list_campaigns(conn),
    }


def record_simulation_event(
    conn,
    campaign_id,
    event_type,
    target_id=None,
    channel=None,
    delivery_status=None,
    metadata=None,
    occurred_at=None,
):
    """Record a lab/demo event and update target rollup fields when possible."""
    normalized_event = (event_type or "").strip().lower()
    event_config = VALID_SIMULATION_EVENTS.get(normalized_event)
    if not event_config:
        raise ValueError("Unsupported simulation event type: {}".format(event_type))

    campaign = _row_to_dict(
        conn.execute(
            "SELECT id, channel FROM simulation_campaigns WHERE id = ?",
            (campaign_id,),
        )
    )
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))

    target = None
    if target_id is not None:
        target = _row_to_dict(
            conn.execute(
                """
                SELECT id, campaign_id, channel, delivery_status
                FROM simulation_targets
                WHERE id = ? AND campaign_id = ?
                """,
                (target_id, campaign_id),
            )
        )
        if not target:
            raise ValueError("Unknown simulation target id: {}".format(target_id))

    event_channel = channel or (target or {}).get("channel") or campaign["channel"]
    event_status = delivery_status or event_config.get("status") or (target or {}).get("delivery_status")
    timestamp = occurred_at or _utc_now()
    metadata_json = json.dumps(metadata or {}, sort_keys=True)

    cursor = conn.execute(
        """
        INSERT INTO simulation_events (
            campaign_id, target_id, channel, event_type, delivery_status,
            occurred_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            target_id,
            event_channel,
            normalized_event,
            event_status,
            timestamp,
            metadata_json,
        ),
    )
    event_id = cursor.lastrowid

    if target_id is not None:
        assignments = [
            "{} = ?".format(event_config["timestamp_column"]),
            "updated_at = ?",
        ]
        values = [timestamp, timestamp]
        target_column = event_config["target_column"]
        if target_column == "delivery_status":
            assignments.insert(0, "delivery_status = ?")
            values.insert(0, event_status or "delivered")
        else:
            assignments.insert(0, "{} = 1".format(target_column))

        values.extend([target_id, campaign_id])
        conn.execute(
            """
            UPDATE simulation_targets
            SET {}
            WHERE id = ? AND campaign_id = ?
            """.format(", ".join(assignments)),
            values,
        )

    conn.commit()
    return get_simulation_event(conn, event_id)


def get_simulation_event(conn, event_id):
    return _row_to_dict(
        conn.execute(
            """
            SELECT
                id,
                campaign_id,
                target_id,
                channel,
                event_type,
                delivery_status,
                occurred_at,
                metadata,
                created_at
            FROM simulation_events
            WHERE id = ?
            """,
            (event_id,),
        )
    )


def list_ai_provider_settings(conn):
    cursor = conn.execute(
        """
        SELECT
            id,
            name,
            provider_type,
            model_name,
            base_url,
            enabled,
            secret_placeholder,
            description,
            created_at,
            updated_at
        FROM ai_provider_configs
        ORDER BY provider_type ASC, name ASC
        """
    )
    return [_provider_response(row) for row in _rows_to_dicts(cursor)]


def update_ai_provider_settings(
    conn,
    provider_id,
    name=None,
    provider_type=None,
    model_name=None,
    base_url=None,
    enabled=None,
    secret=None,
    description=None,
):
    """Update provider metadata without storing or returning secret material."""
    existing = _row_to_dict(
        conn.execute(
            "SELECT * FROM ai_provider_configs WHERE id = ?",
            (provider_id,),
        )
    )
    if not existing:
        raise ValueError("Unknown AI provider config id: {}".format(provider_id))

    now = _utc_now()
    updated = {
        "name": name if name is not None else existing["name"],
        "provider_type": provider_type if provider_type is not None else existing["provider_type"],
        "model_name": model_name if model_name is not None else existing["model_name"],
        "base_url": base_url if base_url is not None else existing["base_url"],
        "enabled": 1 if bool(enabled) else 0 if enabled is not None else existing["enabled"],
        "secret_placeholder": existing["secret_placeholder"],
        "description": description if description is not None else existing["description"],
        "updated_at": now,
    }

    if secret:
        updated["secret_placeholder"] = "configured"

    conn.execute(
        """
        UPDATE ai_provider_configs
        SET
            name = ?,
            provider_type = ?,
            model_name = ?,
            base_url = ?,
            enabled = ?,
            secret_placeholder = ?,
            description = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            updated["name"],
            updated["provider_type"],
            updated["model_name"],
            updated["base_url"],
            updated["enabled"],
            updated["secret_placeholder"],
            updated["description"],
            updated["updated_at"],
            provider_id,
        ),
    )
    conn.commit()

    row = _row_to_dict(
        conn.execute(
            """
            SELECT
                id,
                name,
                provider_type,
                model_name,
                base_url,
                enabled,
                secret_placeholder,
                description,
                created_at,
                updated_at
            FROM ai_provider_configs
            WHERE id = ?
            """,
            (provider_id,),
        )
    )
    return _provider_response(row)
