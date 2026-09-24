from datetime import UTC, datetime, time
import json


REDACTED_VALUE = "[redacted]"

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session",
    "token",
)

SAFE_SECRET_KEY_SUFFIXES = (
    "_placeholder",
    "_reference",
    "placeholder",
    "reference",
)


def _utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _normalize_text(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _safe_json_loads(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _safe_json_dumps(value):
    return json.dumps(value or {}, sort_keys=True)


def _normalize_date_bound(value, end_of_day=False):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    parsed = datetime.strptime(normalized, "%Y-%m-%d")
    if end_of_day:
        parsed = datetime.combine(parsed.date(), time.max)
    return parsed.isoformat(timespec="seconds")


def _is_sensitive_key(key):
    normalized = str(key or "").lower()
    if normalized.endswith(SAFE_SECRET_KEY_SUFFIXES):
        return False
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_audit_metadata(value):
    """Return audit metadata with plaintext secret fields removed recursively."""
    if isinstance(value, dict):
        redacted = {}
        for key, nested in value.items():
            if _is_sensitive_key(key):
                redacted[key] = REDACTED_VALUE
            else:
                redacted[key] = redact_audit_metadata(nested)
        return redacted
    if isinstance(value, list):
        return [redact_audit_metadata(item) for item in value]
    return value


def _audit_event_response(row):
    if not row:
        return None
    event = dict(row)
    event["metadata"] = _safe_json_loads(event.pop("metadata_json", None), {})
    return event


def record_audit_event(
    conn,
    action_type,
    entity_type,
    entity_id=None,
    actor_identity=None,
    channel=None,
    ip_address=None,
    user_agent=None,
    campaign_id=None,
    metadata=None,
    occurred_at=None,
):
    """Record a sanitized administrative audit event and return its id."""
    normalized_action = _normalize_text(action_type)
    normalized_entity_type = _normalize_text(entity_type)
    if not normalized_action:
        raise ValueError("Audit action type is required.")
    if not normalized_entity_type:
        raise ValueError("Audit entity type is required.")

    cursor = conn.execute(
        """
        INSERT INTO administrative_audit_events (
            actor_identity, action_type, entity_type, entity_id, campaign_id,
            channel, ip_address, user_agent, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _normalize_text(actor_identity),
            normalized_action,
            normalized_entity_type,
            _normalize_text(entity_id),
            campaign_id,
            _normalize_text(channel),
            _normalize_text(ip_address),
            _normalize_text(user_agent),
            _safe_json_dumps(redact_audit_metadata(metadata or {})),
            occurred_at or _utc_now(),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def record_campaign_audit(conn, action_type, campaign_id, **kwargs):
    return record_audit_event(conn, action_type, "campaign", entity_id=campaign_id, campaign_id=campaign_id, **kwargs)


def record_target_audit(conn, action_type, target_id, campaign_id=None, **kwargs):
    return record_audit_event(conn, action_type, "target", entity_id=target_id, campaign_id=campaign_id, **kwargs)


def record_ai_provider_audit(conn, action_type, provider_id, **kwargs):
    return record_audit_event(conn, action_type, "ai_provider", entity_id=provider_id, **kwargs)


def record_generation_audit(conn, action_type, generation_id, campaign_id=None, **kwargs):
    return record_audit_event(conn, action_type, "ai_generation", entity_id=generation_id, campaign_id=campaign_id, **kwargs)


def record_delivery_audit(conn, action_type, delivery_job_id, campaign_id=None, channel=None, **kwargs):
    return record_audit_event(
        conn,
        action_type,
        "delivery",
        entity_id=delivery_job_id,
        campaign_id=campaign_id,
        channel=channel,
        **kwargs,
    )


def record_export_audit(conn, action_type, export_id=None, campaign_id=None, **kwargs):
    return record_audit_event(conn, action_type, "export", entity_id=export_id, campaign_id=campaign_id, **kwargs)


def record_directory_sync_audit(conn, action_type, sync_job_id, campaign_id=None, **kwargs):
    return record_audit_event(conn, action_type, "directory_sync", entity_id=sync_job_id, campaign_id=campaign_id, **kwargs)


def list_audit_events(
    conn,
    action_type=None,
    entity_type=None,
    channel=None,
    actor_identity=None,
    campaign_id=None,
    start_date=None,
    end_date=None,
    limit=100,
):
    """Return administrative audit events with metadata already decoded."""
    filters = []
    params = []
    if action_type is not None:
        filters.append("action_type = ?")
        params.append(action_type)
    if entity_type is not None:
        filters.append("entity_type = ?")
        params.append(entity_type)
    if channel is not None:
        filters.append("channel = ?")
        params.append(channel)
    if actor_identity is not None:
        filters.append("actor_identity = ?")
        params.append(actor_identity)
    if campaign_id is not None:
        filters.append("campaign_id = ?")
        params.append(campaign_id)
    if start_date is not None:
        filters.append("created_at >= ?")
        params.append(_normalize_date_bound(start_date))
    if end_date is not None:
        filters.append("created_at <= ?")
        params.append(_normalize_date_bound(end_date, end_of_day=True))
    params.append(int(limit or 100))
    where = "WHERE {}".format(" AND ".join(filters)) if filters else ""
    cursor = conn.execute(
        f"""
        SELECT
            id, actor_identity, action_type, entity_type, entity_id,
            campaign_id, channel, ip_address, user_agent, metadata_json,
            created_at
        FROM administrative_audit_events
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        params,
    )
    columns = [description[0] for description in cursor.description]
    return [_audit_event_response(dict(zip(columns, row))) for row in cursor.fetchall()]


def get_audit_event(conn, audit_event_id):
    cursor = conn.execute(
        """
        SELECT
            id, actor_identity, action_type, entity_type, entity_id,
            campaign_id, channel, ip_address, user_agent, metadata_json,
            created_at
        FROM administrative_audit_events
        WHERE id = ?
        """,
        (audit_event_id,),
    )
    columns = [description[0] for description in cursor.description]
    row = cursor.fetchone()
    if not row:
        return None
    return _audit_event_response(dict(zip(columns, row)))


def audit_filter_options(conn):
    def distinct_values(column):
        rows = conn.execute(
            """
            SELECT DISTINCT {column}
            FROM administrative_audit_events
            WHERE {column} IS NOT NULL AND TRIM({column}) != ''
            ORDER BY {column} ASC
            """.format(column=column)
        ).fetchall()
        return [row[0] for row in rows]

    return {
        "action_types": distinct_values("action_type"),
        "entity_types": distinct_values("entity_type"),
        "channels": distinct_values("channel"),
        "actors": distinct_values("actor_identity"),
    }
