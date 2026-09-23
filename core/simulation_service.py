import csv
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
import hashlib
from io import StringIO
import json
import re
import secrets

from core.db_migration import SIMULATION_DEMO_SLUG


VALID_SIMULATION_CHANNELS = {"email", "sms", "voice"}
VALID_CAMPAIGN_STATUSES = {"draft", "active", "paused", "completed", "archived"}
TARGET_CSV_COLUMNS = {
    "name",
    "display_name",
    "email",
    "phone",
    "department",
    "manager",
    "channel",
    "active",
}


VALID_SIMULATION_EVENTS = {
    "queued": {
        "target_column": "delivery_status",
        "timestamp_column": None,
        "status": "queued",
    },
    "sent": {
        "target_column": "delivery_status",
        "timestamp_column": None,
        "status": "sent",
    },
    "delivered": {
        "target_column": "delivery_status",
        "timestamp_column": "delivered_at",
        "status": "delivered",
    },
    "failed": {
        "target_column": "delivery_status",
        "timestamp_column": None,
        "status": "failed",
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
    "voice_response": {
        "status": "responded",
    },
}

METRIC_EVENT_ALIASES = {
    "queued": "queued",
    "sent": "sent",
    "delivered": "delivered",
    "failed": "failed",
    "open": "opened",
    "opened": "opened",
    "forward": "forwarded",
    "forwarded": "forwarded",
    "delete": "deleted",
    "deleted": "deleted",
    "link_click": "link_clicked",
    "link_clicked": "link_clicked",
    "attachment_open": "attachment_opened",
    "attachment_opened": "attachment_opened",
    "voice_response": "voice_responses",
}
METRIC_COUNT_FIELDS = (
    "queued",
    "sent",
    "delivered",
    "failed",
    "opened",
    "forwarded",
    "deleted",
    "link_clicked",
    "attachment_opened",
    "voice_responses",
)
DELIVERY_STATUS_METRICS = {"queued", "sent", "delivered", "failed"}


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


def _json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def _json_dict(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _audit_response(row):
    if not row:
        return None
    audit = dict(row)
    audit["request"] = _json_dict(audit.pop("request_json", None))
    output_json = audit.pop("output_json", None)
    audit["output"] = _json_dict(output_json) if output_json else None
    audit["risk_flags"] = _json_list(audit.get("risk_flags"))
    audit["safety_notes"] = _json_list(audit.get("safety_notes"))
    audit["metadata"] = _json_dict(audit.get("metadata"))
    return audit


def _ai_draft_response(row):
    if not row:
        return None
    draft = dict(row)
    draft["channels"] = _json_list(draft.get("channels"))
    draft["risk_flags"] = _json_list(draft.get("risk_flags"))
    draft["safety_notes"] = _json_list(draft.get("safety_notes"))
    draft["metadata"] = _json_dict(draft.get("metadata"))
    return draft


def _safe_json_dumps(value):
    return json.dumps(value or {}, sort_keys=True)


def _event_metadata(value):
    if isinstance(value, dict):
        return dict(value)
    return _json_dict(value)


def _content_hash(value):
    return hashlib.sha256(_safe_json_dumps(value).encode("utf-8")).hexdigest()


def _request_audit_payload(request):
    if is_dataclass(request):
        payload = asdict(request)
    else:
        payload = {
            "scenario_goal": getattr(request, "scenario_goal", None),
            "audience": getattr(request, "audience", None),
            "channels": list(getattr(request, "channels", []) or []),
            "tone": getattr(request, "tone", None),
            "difficulty": getattr(request, "difficulty", None),
            "safety_constraints": list(getattr(request, "safety_constraints", []) or []),
            "campaign_context": dict(getattr(request, "campaign_context", {}) or {}),
            "training_reminder": getattr(request, "training_reminder", None),
        }
    payload["channels"] = list(payload.get("channels") or [])
    payload["safety_constraints"] = list(payload.get("safety_constraints") or [])
    payload["campaign_context"] = dict(payload.get("campaign_context") or {})
    return payload


def _response_audit_payload(response):
    return {
        "channels": list(response.channels),
        "draft": asdict(response.draft) if is_dataclass(response.draft) else {},
    }


def ai_generation_response_payload(response):
    """Return API-safe generated draft content without provider credential material."""
    draft = asdict(response.draft) if is_dataclass(response.draft) else {}
    return {
        "provider": {
            "id": response.provider_id,
            "name": response.provider_name,
            "provider_type": response.provider_type,
            "model_name": response.model_name,
        },
        "channels": list(response.channels),
        "draft": draft,
        "risk_flags": list(response.risk_flags or []),
        "safety_notes": list(response.safety_notes or []),
        "metadata": dict(response.metadata or {}),
    }


def _record_ai_generation_audit(
    conn,
    provider,
    request,
    response=None,
    status="generated",
    error_reason=None,
    risk_flags=None,
):
    flags = risk_flags if risk_flags is not None else getattr(response, "risk_flags", [])
    notes = getattr(response, "safety_notes", [])
    metadata = getattr(response, "metadata", {})
    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO ai_generation_audits (
            provider_id, provider_name, provider_type, model_name, request_json,
            output_json, risk_flags, safety_notes, metadata, status,
            error_reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider.get("id") if provider else None,
            provider.get("name") if provider else None,
            provider.get("provider_type") if provider else None,
            provider.get("model_name") if provider else None,
            _safe_json_dumps(_request_audit_payload(request)),
            _safe_json_dumps(_response_audit_payload(response)) if response else None,
            json.dumps(list(flags or []), sort_keys=True),
            json.dumps(list(notes or []), sort_keys=True),
            _safe_json_dumps(metadata),
            status,
            _normalize_text(error_reason),
            now,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _normalize_text(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_status(status):
    normalized = (_normalize_text(status) or "draft").lower()
    if normalized not in VALID_CAMPAIGN_STATUSES:
        raise ValueError("Campaign status must be one of: {}".format(", ".join(sorted(VALID_CAMPAIGN_STATUSES))))
    return normalized


def _normalize_channels(channels=None, channel=None):
    values = []
    if isinstance(channels, str):
        try:
            parsed = json.loads(channels)
            values = parsed if isinstance(parsed, list) else [channels]
        except ValueError:
            values = channels.split(",")
    elif channels:
        values = list(channels)
    elif channel:
        values = [channel]
    else:
        values = ["email"]

    normalized = []
    for value in values:
        channel_value = (_normalize_text(value) or "").lower()
        if not channel_value:
            continue
        if channel_value not in VALID_SIMULATION_CHANNELS:
            raise ValueError("Channel must be one of: {}".format(", ".join(sorted(VALID_SIMULATION_CHANNELS))))
        if channel_value not in normalized:
            normalized.append(channel_value)

    if not normalized:
        raise ValueError("At least one campaign channel is required.")
    return normalized


def _normalize_email(email):
    normalized = (_normalize_text(email) or "").lower()
    if not normalized:
        return None
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized):
        raise ValueError("Email address must be a valid address such as user@example.com.")
    return normalized


def _normalize_phone(phone):
    normalized = _normalize_text(phone)
    if not normalized:
        return None
    compact = re.sub(r"[\s().-]+", "", normalized)
    if not re.match(r"^\+?\d+$", compact):
        raise ValueError("Phone number may only contain digits, spaces, punctuation, and an optional leading +.")
    digits = re.sub(r"\D", "", compact)
    if len(digits) < 7 or len(digits) > 15:
        raise ValueError("Phone number must contain 7 to 15 digits.")
    return compact


def _normalize_active(active):
    if isinstance(active, str):
        return 0 if active.strip().lower() in {"0", "false", "no", "off", "inactive"} else 1
    return 1 if active is None or bool(active) else 0


def _normalize_target_payload(payload, default_channel="email", source="manual"):
    payload = payload or {}
    name = _normalize_text(payload.get("name")) or _normalize_text(payload.get("display_name"))
    display_name = _normalize_text(payload.get("display_name")) or name
    email = _normalize_email(payload.get("email"))
    phone = _normalize_phone(payload.get("phone"))
    channel = (_normalize_text(payload.get("channel")) or default_channel or "email").lower()

    if channel not in VALID_SIMULATION_CHANNELS:
        raise ValueError("Target channel must be one of: {}".format(", ".join(sorted(VALID_SIMULATION_CHANNELS))))
    if not name:
        raise ValueError("Target name is required.")
    if not email and not phone:
        raise ValueError("Target requires at least one contact method: email or phone number.")
    if channel == "email" and not email:
        raise ValueError("Email channel targets require an email address.")
    if channel in {"sms", "voice"} and not phone:
        raise ValueError("{} channel targets require a phone number.".format(channel.upper()))

    return {
        "name": name,
        "display_name": display_name,
        "email": email,
        "phone": phone,
        "department": _normalize_text(payload.get("department")),
        "manager": _normalize_text(payload.get("manager")),
        "source": _normalize_text(payload.get("source")) or source,
        "active": _normalize_active(payload.get("active")),
        "channel": channel,
    }


def _slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "simulation-campaign"


def _unique_campaign_slug(conn, name, campaign_id=None):
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 2
    while True:
        params = [slug]
        query = "SELECT id FROM simulation_campaigns WHERE slug = ?"
        if campaign_id is not None:
            query += " AND id != ?"
            params.append(campaign_id)
        existing = _row_to_dict(conn.execute(query, params))
        if not existing:
            return slug
        slug = "{}-{}".format(base_slug, suffix)
        suffix += 1


def _provider_response(row):
    provider = dict(row)
    provider["enabled"] = _bool(provider.get("enabled"))
    provider["secret_configured"] = provider.get("secret_placeholder") == "configured"
    provider.pop("secret_placeholder", None)
    return provider


def _delivery_provider_response(row):
    provider = dict(row)
    provider["enabled"] = _bool(provider.get("enabled"))
    provider["settings"] = _json_dict(provider.pop("settings_json", None))
    provider["required_settings"] = _json_list(provider.pop("required_settings_json", None))
    provider["secret_configured"] = provider.get("secret_placeholder") == "configured"
    provider.pop("secret_placeholder", None)
    return provider


def _directory_provider_response(row):
    provider = dict(row)
    provider["enabled"] = _bool(provider.get("enabled"))
    provider["consented_scopes"] = _json_list(provider.pop("consented_scopes_json", None))
    provider["selected_groups"] = _json_list(provider.pop("selected_groups_json", None))
    provider["field_mapping"] = _json_dict(provider.pop("field_mapping_json", None))
    provider["settings"] = _json_dict(provider.pop("settings_json", None))
    provider["secret_configured"] = provider.get("secret_placeholder") == "configured"
    provider.pop("secret_placeholder", None)
    return provider


def _directory_sync_job_response(row):
    if not row:
        return None
    job = dict(row)
    job["selected_groups"] = _json_list(job.pop("selected_groups_json", None))
    job["validation_errors"] = _json_list(job.pop("validation_errors_json", None))
    return job


def _staged_directory_user_response(row):
    if not row:
        return None
    user = dict(row)
    user["business_phones"] = _json_list(user.pop("business_phones_json", None))
    user["groups"] = _json_list(user.pop("groups_json", None))
    user["source_group_ids"] = _json_list(user.pop("source_group_ids_json", None))
    user["validation_errors"] = _json_list(user.pop("validation_errors_json", None))
    user["target_payload"] = _json_dict(user.pop("target_payload_json", None))
    user["active"] = _bool(user.get("active"))
    return user


def _directory_sync_audit_event_response(row):
    if not row:
        return None
    event = dict(row)
    event["metadata"] = _json_dict(event.pop("metadata_json", None))
    return event


def _delivery_job_response(row):
    if not row:
        return None
    job = dict(row)
    job["provider_snapshot"] = _json_dict(job.get("provider_snapshot"))
    return job


def _message_artifact_response(row):
    artifact = dict(row)
    artifact["content"] = _json_dict(artifact.pop("content_json", None))
    return artifact


def _tracking_token_response(row):
    return dict(row)


def _delivery_attempt_response(row):
    attempt = dict(row)
    attempt["provider_response"] = _json_dict(attempt.get("provider_response"))
    return attempt


def _campaign_response(row):
    if not row:
        return None
    campaign = dict(row)
    campaign["selected_channels"] = _json_list(campaign.get("selected_channels"))
    campaign["archived"] = campaign.get("archived_at") is not None
    return campaign


def _target_response(row):
    if not row:
        return None
    target = dict(row)
    for field in ("opened", "forwarded", "deleted", "link_clicked", "attachment_opened", "active"):
        if field in target:
            target[field] = _bool(target[field])
    target["archived"] = target.get("archived_at") is not None
    return target


def list_campaigns(conn, include_archived=False):
    """Return simulation campaigns with target counts for dashboard summaries."""
    where = "" if include_archived else "WHERE c.archived_at IS NULL"
    cursor = conn.execute(
        f"""
        SELECT
            c.id,
            c.slug,
            c.name,
            c.description,
            c.objective,
            c.training_owner,
            c.channel,
            c.selected_channels,
            c.status,
            c.authorized_scope,
            c.landing_url,
            c.training_url,
            c.start_date,
            c.end_date,
            c.started_at,
            c.completed_at,
            c.archived_at,
            c.created_at,
            c.updated_at,
            COUNT(t.id) AS target_count
        FROM simulation_campaigns c
        LEFT JOIN simulation_targets t ON t.campaign_id = c.id
        {where}
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        """
    )
    return [_campaign_response(row) for row in _rows_to_dicts(cursor)]


def get_campaign(conn, campaign_id):
    campaign = _row_to_dict(
        conn.execute(
            """
            SELECT
                id, slug, name, description, objective, training_owner, channel,
                selected_channels, status, authorized_scope, landing_url,
                training_url, start_date, end_date, started_at, completed_at,
                archived_at, created_at, updated_at
            FROM simulation_campaigns
            WHERE id = ?
            """,
            (campaign_id,),
        )
    )
    return _campaign_response(campaign)


def create_campaign(
    conn,
    name,
    description=None,
    objective=None,
    training_owner=None,
    status="draft",
    selected_channels=None,
    landing_url=None,
    training_url=None,
    start_date=None,
    end_date=None,
    authorized_scope=None,
):
    """Create a campaign record and return the normalized row."""
    normalized_name = _normalize_text(name)
    if not normalized_name:
        raise ValueError("Campaign name is required.")

    channels = _normalize_channels(selected_channels)
    primary_channel = channels[0]
    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO simulation_campaigns (
            slug, name, description, objective, training_owner, channel,
            selected_channels, status, authorized_scope, landing_url,
            training_url, start_date, end_date, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _unique_campaign_slug(conn, normalized_name),
            normalized_name,
            _normalize_text(description),
            _normalize_text(objective),
            _normalize_text(training_owner),
            primary_channel,
            json.dumps(channels),
            _normalize_status(status),
            _normalize_text(authorized_scope),
            _normalize_text(landing_url),
            _normalize_text(training_url),
            _normalize_text(start_date),
            _normalize_text(end_date),
            now,
            now,
        ),
    )
    conn.commit()
    return get_campaign(conn, cursor.lastrowid)


def update_campaign(conn, campaign_id, **fields):
    """Update editable campaign metadata."""
    existing = get_campaign(conn, campaign_id)
    if not existing:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))

    channels = _normalize_channels(fields.get("selected_channels", existing["selected_channels"]))
    name = _normalize_text(fields.get("name", existing["name"]))
    if not name:
        raise ValueError("Campaign name is required.")

    updated = {
        "slug": _unique_campaign_slug(conn, name, campaign_id=campaign_id),
        "name": name,
        "description": _normalize_text(fields.get("description", existing.get("description"))),
        "objective": _normalize_text(fields.get("objective", existing.get("objective"))),
        "training_owner": _normalize_text(fields.get("training_owner", existing.get("training_owner"))),
        "channel": channels[0],
        "selected_channels": json.dumps(channels),
        "status": _normalize_status(fields.get("status", existing.get("status"))),
        "authorized_scope": _normalize_text(fields.get("authorized_scope", existing.get("authorized_scope"))),
        "landing_url": _normalize_text(fields.get("landing_url", existing.get("landing_url"))),
        "training_url": _normalize_text(fields.get("training_url", existing.get("training_url"))),
        "start_date": _normalize_text(fields.get("start_date", existing.get("start_date"))),
        "end_date": _normalize_text(fields.get("end_date", existing.get("end_date"))),
        "updated_at": _utc_now(),
    }

    conn.execute(
        """
        UPDATE simulation_campaigns
        SET
            slug = ?, name = ?, description = ?, objective = ?,
            training_owner = ?, channel = ?, selected_channels = ?,
            status = ?, authorized_scope = ?, landing_url = ?,
            training_url = ?, start_date = ?, end_date = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            updated["slug"],
            updated["name"],
            updated["description"],
            updated["objective"],
            updated["training_owner"],
            updated["channel"],
            updated["selected_channels"],
            updated["status"],
            updated["authorized_scope"],
            updated["landing_url"],
            updated["training_url"],
            updated["start_date"],
            updated["end_date"],
            updated["updated_at"],
            campaign_id,
        ),
    )
    conn.commit()
    return get_campaign(conn, campaign_id)


def archive_campaign(conn, campaign_id):
    """Soft archive a campaign without deleting targets, events, or metrics."""
    if not get_campaign(conn, campaign_id):
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))
    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_campaigns
        SET status = 'archived', archived_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, campaign_id),
    )
    conn.commit()
    return get_campaign(conn, campaign_id)


def _reporting_event_source(event):
    metadata = _event_metadata(event.get("metadata"))
    provider = _normalize_text(event.get("provider"))
    provider_reference_id = _normalize_text(event.get("provider_reference_id"))
    provider_event_id = _normalize_text(event.get("provider_event_id"))
    mode = (_normalize_text(metadata.get("mode")) or "").lower()
    source = (_normalize_text(metadata.get("source")) or "").lower()

    if mode == "dry_run" or (provider and provider.startswith("dry_run")):
        return {
            "label": "Dry-run",
            "badge": "info",
            "description": "Recorded by a dry-run delivery job without external traffic.",
        }
    if provider or provider_event_id or provider_reference_id:
        return {
            "label": "Real provider",
            "badge": "success",
            "description": "Recorded from a configured delivery provider or provider webhook.",
        }
    if source:
        return {
            "label": "Simulated",
            "badge": "secondary",
            "description": "Recorded by internal simulation tracking or test tooling.",
        }
    return {
        "label": "Simulated",
        "badge": "secondary",
        "description": "Recorded as an internal simulation event.",
    }


def _campaign_reporting(metrics, events, campaign_id):
    annotated_events = []
    events_by_target = {}
    source_counts = {}
    for event in events:
        annotated = dict(event)
        annotated["metadata"] = _event_metadata(event.get("metadata"))
        annotated["source"] = _reporting_event_source(event)
        source_counts[annotated["source"]["label"]] = source_counts.get(annotated["source"]["label"], 0) + 1
        annotated_events.append(annotated)
        if annotated.get("target_id") is not None:
            events_by_target.setdefault(annotated["target_id"], []).append(annotated)

    funnel_fields = (
        ("queued", "Queued", "Targets queued for delivery"),
        ("sent", "Sent", "Targets sent by the delivery layer"),
        ("delivered", "Delivered", "Targets with confirmed delivery"),
        ("failed", "Failed", "Targets with failed delivery"),
        ("opened", "Opened", "Targets that opened a message"),
        ("forwarded", "Forwarded", "Targets that forwarded a message"),
        ("deleted", "Deleted", "Targets that deleted a message"),
        ("link_clicked", "Clicked", "Targets that clicked a tracked link"),
        ("attachment_opened", "Attachment", "Targets that opened a tracked attachment"),
        ("voice_responses", "Voice response", "Voice targets with recorded responses"),
    )
    aggregate = metrics["aggregate"]
    delivery_funnel = [
        {
            "field": field,
            "label": label,
            "description": description,
            "count": aggregate.get(field, 0),
            "rate": aggregate.get("{}_rate".format(field), 0.0),
            "target_anchor": "targets",
            "event_anchor": "events",
        }
        for field, label, description in funnel_fields
    ]

    channel_rows = []
    for channel, bucket in metrics["channels"].items():
        row = dict(bucket)
        row["channel"] = channel
        row["metrics_url"] = "/simulations/metrics?campaign_id={}&channel={}".format(campaign_id, channel)
        channel_rows.append(row)

    target_activity = []
    for target in metrics["targets"]:
        row = dict(target)
        history = events_by_target.get(target.get("target_id"), [])
        row["history"] = history[:6]
        row["event_count"] = len(history)
        target_activity.append(row)

    return {
        "delivery_funnel": delivery_funnel,
        "channels": channel_rows,
        "target_activity": target_activity,
        "events": annotated_events,
        "source_counts": source_counts,
    }


def get_campaign_detail(conn, campaign_id, include_archived_targets=True):
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))
    targets = list_targets(conn, campaign_id, include_archived=include_archived_targets)
    _attach_latest_target_events(conn, targets)
    metrics = get_campaign_metrics(conn, campaign_id)
    events = list_simulation_events(conn, campaign_id)
    return {
        "campaign": campaign,
        "targets": targets,
        "metrics": metrics,
        "import_batches": list_import_batches(conn, campaign_id),
        "events": events,
        "reporting": _campaign_reporting(metrics, events, campaign_id),
        "ai_drafts": list_ai_campaign_drafts(conn, campaign_id),
        "delivery_providers": list_delivery_provider_settings(conn),
        "delivery_preview": build_delivery_preview(conn, campaign_id, mode="dry_run"),
        "delivery_jobs": list_delivery_jobs(conn, campaign_id=campaign_id),
    }


def _attach_latest_target_events(conn, targets):
    if not targets:
        return
    target_ids = [target["id"] for target in targets]
    placeholders = ",".join("?" for _ in target_ids)
    events = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT e.*
            FROM simulation_events e
            JOIN (
                SELECT target_id, MAX(id) AS latest_event_id
                FROM simulation_events
                WHERE target_id IN ({placeholders})
                GROUP BY target_id
            ) latest ON latest.latest_event_id = e.id
            """,
            target_ids,
        )
    )
    latest_by_target = {event["target_id"]: event for event in events}
    for target in targets:
        target["latest_event"] = latest_by_target.get(target["id"])


def list_simulation_events(conn, campaign_id=None):
    """Return simulation events for campaign detail and audit views."""
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE e.campaign_id = ?"
        params.append(campaign_id)
    return _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                e.id,
                e.campaign_id,
                e.target_id,
                t.display_name AS target_display_name,
                t.name AS target_name,
                e.channel,
                e.event_type,
                e.delivery_status,
                e.delivery_job_id,
                e.delivery_attempt_id,
                e.tracking_token_id,
                e.provider_reference_id,
                e.provider,
                e.provider_event_id,
                e.error_message,
                e.retry_count,
                e.occurred_at,
                e.metadata,
                e.created_at
            FROM simulation_events e
            LEFT JOIN simulation_targets t ON t.id = e.target_id
            {where}
            ORDER BY e.occurred_at DESC, e.id DESC
            """,
            params,
        )
    )


def list_targets(conn, campaign_id=None, include_archived=False):
    """Return targets for one campaign or all campaigns."""
    params = []
    filters = []
    if campaign_id is not None:
        filters.append("t.campaign_id = ?")
        params.append(campaign_id)
    if not include_archived:
        filters.append("t.archived_at IS NULL")
    where = "WHERE {}".format(" AND ".join(filters)) if filters else ""

    cursor = conn.execute(
        f"""
        SELECT
            t.id,
            t.campaign_id,
            c.name AS campaign_name,
            t.name,
            t.display_name,
            t.email,
            t.phone,
            t.department,
            t.manager,
            t.source,
            t.active,
            t.import_batch_id,
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
            t.archived_at,
            t.created_at,
            t.updated_at
        FROM simulation_targets t
        JOIN simulation_campaigns c ON c.id = t.campaign_id
        {where}
        ORDER BY t.id ASC
        """,
        params,
    )
    return [_target_response(row) for row in _rows_to_dicts(cursor)]


def get_target(conn, target_id):
    target = _row_to_dict(
        conn.execute(
            """
            SELECT
                t.id, t.campaign_id, c.name AS campaign_name, t.name,
                t.display_name, t.email, t.phone, t.department, t.manager,
                t.source, t.active, t.import_batch_id, t.channel,
                t.delivery_status, t.opened, t.forwarded, t.deleted,
                t.link_clicked, t.attachment_opened, t.delivered_at,
                t.opened_at, t.forwarded_at, t.deleted_at, t.link_clicked_at,
                t.attachment_opened_at, t.archived_at, t.created_at, t.updated_at
            FROM simulation_targets t
            JOIN simulation_campaigns c ON c.id = t.campaign_id
            WHERE t.id = ?
            """,
            (target_id,),
        )
    )
    return _target_response(target)


def create_target(conn, campaign_id, **fields):
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))
    payload = _normalize_target_payload(fields, default_channel=campaign["channel"], source=fields.get("source", "manual"))
    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO simulation_targets (
            campaign_id, name, display_name, email, phone, department,
            manager, source, active, import_batch_id, channel,
            delivery_status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            campaign_id,
            payload["name"],
            payload["display_name"],
            payload["email"],
            payload["phone"],
            payload["department"],
            payload["manager"],
            payload["source"],
            payload["active"],
            fields.get("import_batch_id"),
            payload["channel"],
            now,
            now,
        ),
    )
    conn.commit()
    return get_target(conn, cursor.lastrowid)


def update_target(conn, target_id, **fields):
    existing = get_target(conn, target_id)
    if not existing:
        raise ValueError("Unknown simulation target id: {}".format(target_id))

    payload = {
        "name": fields.get("name", existing["name"]),
        "display_name": fields.get("display_name", existing["display_name"]),
        "email": fields.get("email", existing["email"]),
        "phone": fields.get("phone", existing["phone"]),
        "department": fields.get("department", existing["department"]),
        "manager": fields.get("manager", existing["manager"]),
        "source": fields.get("source", existing["source"]),
        "active": fields.get("active", existing["active"]),
        "channel": fields.get("channel", existing["channel"]),
    }
    normalized = _normalize_target_payload(payload, default_channel=existing["channel"], source=existing["source"])
    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_targets
        SET
            name = ?, display_name = ?, email = ?, phone = ?,
            department = ?, manager = ?, source = ?, active = ?,
            channel = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            normalized["name"],
            normalized["display_name"],
            normalized["email"],
            normalized["phone"],
            normalized["department"],
            normalized["manager"],
            normalized["source"],
            normalized["active"],
            normalized["channel"],
            now,
            target_id,
        ),
    )
    conn.commit()
    return get_target(conn, target_id)


def archive_target(conn, target_id):
    if not get_target(conn, target_id):
        raise ValueError("Unknown simulation target id: {}".format(target_id))
    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_targets
        SET active = 0, archived_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, target_id),
    )
    conn.commit()
    return get_target(conn, target_id)


def list_import_batches(conn, campaign_id=None):
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE campaign_id = ?"
        params.append(campaign_id)
    rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                id, campaign_id, original_filename, stored_filename, source,
                status, total_rows, valid_rows, invalid_rows, imported_rows,
                validation_errors, created_at, updated_at, completed_at
            FROM simulation_import_batches
            {where}
            ORDER BY created_at DESC, id DESC
            """,
            params,
        )
    )
    for row in rows:
        row["validation_errors"] = _json_list(row.get("validation_errors"))
    return rows


def parse_target_csv(csv_content, default_channel="email"):
    """Parse target CSV content and return valid rows plus displayable errors."""
    content = csv_content.decode("utf-8-sig") if isinstance(csv_content, bytes) else str(csv_content or "")
    stream = StringIO(content)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        return {
            "rows": [],
            "errors": [{"row": 1, "message": "CSV file must include a header row."}],
            "total_rows": 0,
        }

    headers = {(_normalize_text(header) or "").lower() for header in reader.fieldnames}
    unknown_headers = sorted(header for header in headers if header and header not in TARGET_CSV_COLUMNS)
    header_errors = [
        {
            "row": 1,
            "message": "Unsupported CSV column: {}".format(header),
        }
        for header in unknown_headers
    ]

    rows = []
    errors = list(header_errors)
    seen_contacts = set()
    total_rows = 0

    for row_number, row in enumerate(reader, start=2):
        total_rows += 1
        normalized_row = {
            (_normalize_text(key) or "").lower(): value
            for key, value in row.items()
            if key is not None
        }
        try:
            payload = _normalize_target_payload(normalized_row, default_channel=default_channel, source="csv")
            contact_key = (
                payload["email"] or "",
                payload["phone"] or "",
                payload["channel"],
            )
            if contact_key in seen_contacts:
                raise ValueError("Duplicate target contact in CSV.")
            seen_contacts.add(contact_key)
            payload["row_number"] = row_number
            rows.append(payload)
        except ValueError as exc:
            errors.append({"row": row_number, "message": str(exc)})

    return {
        "rows": rows,
        "errors": errors,
        "total_rows": total_rows,
    }


def import_targets_csv(conn, campaign_id, csv_content, original_filename=None, stored_filename=None):
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))

    parsed = parse_target_csv(csv_content, default_channel=campaign["channel"])
    existing_contacts = {
        (target.get("email") or "", target.get("phone") or "", target.get("channel"))
        for target in list_targets(conn, campaign_id, include_archived=False)
    }
    importable_rows = []
    errors = list(parsed["errors"])
    for row in parsed["rows"]:
        contact_key = (row["email"] or "", row["phone"] or "", row["channel"])
        if contact_key in existing_contacts:
            errors.append({
                "row": row["row_number"],
                "message": "Duplicate target contact already exists in this campaign.",
            })
        else:
            existing_contacts.add(contact_key)
            importable_rows.append(row)

    now = _utc_now()
    status = "completed" if not errors else "completed_with_errors"
    cursor = conn.execute(
        """
        INSERT INTO simulation_import_batches (
            campaign_id, original_filename, stored_filename, source, status,
            total_rows, valid_rows, invalid_rows, imported_rows,
            validation_errors, created_at, updated_at, completed_at
        )
        VALUES (?, ?, ?, 'csv', ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            _normalize_text(original_filename),
            _normalize_text(stored_filename),
            status,
            parsed["total_rows"],
            len(importable_rows),
            len(errors),
            json.dumps(errors, sort_keys=True),
            now,
            now,
            now,
        ),
    )
    batch_id = cursor.lastrowid

    imported = []
    for row in importable_rows:
        target = create_target(
            conn,
            campaign_id,
            name=row["name"],
            display_name=row["display_name"],
            email=row["email"],
            phone=row["phone"],
            department=row["department"],
            manager=row["manager"],
            source="csv",
            active=row["active"],
            channel=row["channel"],
            import_batch_id=batch_id,
        )
        imported.append(target)

    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_import_batches
        SET imported_rows = ?, updated_at = ?
        WHERE id = ?
        """,
        (len(imported), now, batch_id),
    )
    conn.commit()
    return {
        "batch": list_import_batches(conn, campaign_id)[0],
        "targets": imported,
        "errors": errors,
    }


def _metric_bucket(total_targets=0):
    bucket = {"total_targets": int(total_targets or 0)}
    for field in METRIC_COUNT_FIELDS:
        bucket[field] = 0
        bucket["{}_rate".format(field)] = 0.0
    return bucket


def _increment_metric(bucket, metric):
    if metric in METRIC_COUNT_FIELDS:
        bucket[metric] = int(bucket.get(metric) or 0) + 1


def _finalize_metric_bucket(bucket):
    denominator = int(bucket.get("total_targets") or 0)
    for field in METRIC_COUNT_FIELDS:
        bucket[field] = int(bucket.get(field) or 0)
        bucket["{}_rate".format(field)] = round(bucket[field] / denominator, 4) if denominator else 0.0
    return bucket


def _department_key(value):
    return _normalize_text(value) or "Unassigned"


def _normalize_metric_filters(filters=None):
    filters = filters or {}
    normalized = {}

    channel_values = filters.get("channels", filters.get("channel"))
    if isinstance(channel_values, str):
        channel_values = channel_values.split(",")
    channels = []
    for value in channel_values or []:
        channel = (_normalize_text(value) or "").lower()
        if not channel:
            continue
        if channel not in VALID_SIMULATION_CHANNELS:
            raise ValueError("Channel must be one of: {}".format(", ".join(sorted(VALID_SIMULATION_CHANNELS))))
        if channel not in channels:
            channels.append(channel)
    if channels:
        normalized["channels"] = channels

    for key in ("department", "delivery_status", "start_date", "end_date"):
        value = _normalize_text(filters.get(key))
        if value:
            normalized[key] = value

    if filters.get("active_campaigns_only"):
        normalized["active_campaigns_only"] = True

    return normalized


def _date_in_metric_range(value, filters):
    if not value:
        return False
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    text_value = str(value)
    if start_date and text_value < start_date:
        return False
    if end_date and text_value[:10] > end_date[:10]:
        return False
    return True


def _metric_date_filter_active(filters):
    return bool(filters.get("start_date") or filters.get("end_date"))


def _normalized_metric_event(event_type):
    return METRIC_EVENT_ALIASES.get((_normalize_text(event_type) or "").lower())


def _target_metric_from_rollup(target, metric, filters=None):
    filters = filters or {}
    if metric in DELIVERY_STATUS_METRICS:
        if _metric_date_filter_active(filters):
            if metric == "delivered":
                return target.get("delivery_status") == metric and _date_in_metric_range(target.get("delivered_at"), filters)
            return False
        return target.get("delivery_status") == metric
    if metric == "opened":
        return target.get("opened") and (
            not _metric_date_filter_active(filters) or _date_in_metric_range(target.get("opened_at"), filters)
        )
    if metric == "forwarded":
        return target.get("forwarded") and (
            not _metric_date_filter_active(filters) or _date_in_metric_range(target.get("forwarded_at"), filters)
        )
    if metric == "deleted":
        return target.get("deleted") and (
            not _metric_date_filter_active(filters) or _date_in_metric_range(target.get("deleted_at"), filters)
        )
    if metric == "link_clicked":
        return target.get("link_clicked") and (
            not _metric_date_filter_active(filters) or _date_in_metric_range(target.get("link_clicked_at"), filters)
        )
    if metric == "attachment_opened":
        return target.get("attachment_opened") and (
            not _metric_date_filter_active(filters) or _date_in_metric_range(target.get("attachment_opened_at"), filters)
        )
    return False


def _fetch_metric_targets(conn, campaign_id=None, filters=None):
    filters = filters or {}
    params = []
    clauses = []
    if campaign_id is not None:
        clauses.append("t.campaign_id = ?")
        params.append(campaign_id)
    if filters.get("channels"):
        placeholders = ",".join("?" for _ in filters["channels"])
        clauses.append("t.channel IN ({})".format(placeholders))
        params.extend(filters["channels"])
    if filters.get("department"):
        clauses.append("COALESCE(NULLIF(TRIM(t.department), ''), 'Unassigned') = ?")
        params.append(filters["department"])
    if filters.get("delivery_status"):
        clauses.append("t.delivery_status = ?")
        params.append(filters["delivery_status"])
    if filters.get("active_campaigns_only"):
        clauses.append("c.status = 'active'")
        clauses.append("c.archived_at IS NULL")
    where = "WHERE {}".format(" AND ".join(clauses)) if clauses else ""
    rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                t.id,
                t.campaign_id,
                c.name AS campaign_name,
                t.name,
                t.display_name,
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
                t.archived_at
            FROM simulation_targets t
            JOIN simulation_campaigns c ON c.id = t.campaign_id
            {where}
            ORDER BY t.id ASC
            """,
            params,
        )
    )
    return [_target_response(row) for row in rows]


def _fetch_metric_events(conn, campaign_id=None, filters=None):
    filters = filters or {}
    params = []
    clauses = []
    if campaign_id is not None:
        clauses.append("e.campaign_id = ?")
        params.append(campaign_id)
    if filters.get("channels"):
        placeholders = ",".join("?" for _ in filters["channels"])
        clauses.append("e.channel IN ({})".format(placeholders))
        params.extend(filters["channels"])
    if filters.get("department"):
        clauses.append("COALESCE(NULLIF(TRIM(t.department), ''), 'Unassigned') = ?")
        params.append(filters["department"])
    if filters.get("delivery_status"):
        clauses.append("COALESCE(e.delivery_status, t.delivery_status) = ?")
        params.append(filters["delivery_status"])
    if filters.get("start_date"):
        clauses.append("e.occurred_at >= ?")
        params.append(filters["start_date"])
    if filters.get("end_date"):
        clauses.append("substr(e.occurred_at, 1, 10) <= ?")
        params.append(filters["end_date"][:10])
    if filters.get("active_campaigns_only"):
        clauses.append("c.status = 'active'")
        clauses.append("c.archived_at IS NULL")
    where = "WHERE {}".format(" AND ".join(clauses)) if clauses else ""
    return _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                e.id,
                e.campaign_id,
                e.target_id,
                e.channel,
                e.event_type,
                e.delivery_status,
                e.occurred_at,
                e.metadata
            FROM simulation_events e
            JOIN simulation_campaigns c ON c.id = e.campaign_id
            LEFT JOIN simulation_targets t ON t.id = e.target_id
            {where}
            ORDER BY e.occurred_at ASC, e.id ASC
            """,
            params,
        )
    )


def _build_metric_summary(conn, campaign_id=None, filters=None):
    filters = _normalize_metric_filters(filters)
    targets = _fetch_metric_targets(conn, campaign_id, filters)
    target_metrics = {}
    by_channel = {}
    by_department = {}
    seen_target_metrics = set()
    untargeted_events = []

    for target in targets:
        bucket = _metric_bucket(total_targets=1)
        bucket.update({
            "target_id": target["id"],
            "campaign_id": target["campaign_id"],
            "campaign_name": target.get("campaign_name"),
            "name": target.get("name"),
            "display_name": target.get("display_name") or target.get("name"),
            "email": target.get("email"),
            "phone": target.get("phone"),
            "department": target.get("department"),
            "channel": target.get("channel"),
            "delivery_status": target.get("delivery_status"),
            "archived": target.get("archived"),
        })
        target_metrics[target["id"]] = bucket
        channel = target.get("channel") or "unknown"
        department = _department_key(target.get("department"))
        by_channel.setdefault(channel, _metric_bucket())
        by_channel[channel]["total_targets"] += 1
        by_department.setdefault(department, _metric_bucket())
        by_department[department]["total_targets"] += 1

    for event in _fetch_metric_events(conn, campaign_id, filters):
        metric = _normalized_metric_event(event.get("event_type"))
        if not metric:
            continue
        target_id = event.get("target_id")
        if target_id in target_metrics:
            key = (target_id, metric)
            if key in seen_target_metrics:
                continue
            seen_target_metrics.add(key)
            _increment_metric(target_metrics[target_id], metric)
        else:
            untargeted_events.append(event)

    for target in targets:
        target_bucket = target_metrics[target["id"]]
        for metric in METRIC_COUNT_FIELDS:
            if target_bucket.get(metric):
                continue
            if _target_metric_from_rollup(target, metric, filters):
                target_bucket[metric] = 1

        channel = target.get("channel") or "unknown"
        department = _department_key(target.get("department"))
        for metric in METRIC_COUNT_FIELDS:
            count = int(target_bucket.get(metric) or 0)
            by_channel[channel][metric] += count
            by_department[department][metric] += count

    for event in untargeted_events:
        metric = _normalized_metric_event(event.get("event_type"))
        if metric != "voice_responses":
            continue
        channel = event.get("channel") or "unknown"
        by_channel.setdefault(channel, _metric_bucket())
        by_channel[channel][metric] += 1

    aggregate = _metric_bucket(total_targets=len(targets))
    for target_bucket in target_metrics.values():
        for metric in METRIC_COUNT_FIELDS:
            aggregate[metric] += int(target_bucket.get(metric) or 0)
    for event in untargeted_events:
        if _normalized_metric_event(event.get("event_type")) == "voice_responses":
            aggregate["voice_responses"] += 1

    return {
        "aggregate": _finalize_metric_bucket(aggregate),
        "channels": {
            channel: _finalize_metric_bucket(bucket)
            for channel, bucket in sorted(by_channel.items())
        },
        "departments": {
            department: _finalize_metric_bucket(bucket)
            for department, bucket in sorted(by_department.items())
        },
        "targets": [
            _finalize_metric_bucket(target_metrics[target["id"]])
            for target in targets
        ],
    }


def get_channel_metrics(conn, campaign_id=None, filters=None):
    """Return normalized channel-level simulation metrics."""
    return _build_metric_summary(conn, campaign_id, filters)["channels"]


def get_department_metrics(conn, campaign_id=None, filters=None):
    """Return normalized department-level simulation metrics."""
    return _build_metric_summary(conn, campaign_id, filters)["departments"]


def get_target_metrics(conn, campaign_id=None, filters=None):
    """Return normalized target-level simulation metrics."""
    return _build_metric_summary(conn, campaign_id, filters)["targets"]


def get_campaign_metrics(conn, campaign_id=None, filters=None):
    """Calculate normalized campaign metrics from events with target rollup fallback."""
    filters = _normalize_metric_filters(filters)
    metrics = _build_metric_summary(conn, campaign_id, filters)
    campaigns = list_campaigns(conn)
    if filters.get("active_campaigns_only"):
        campaigns = [campaign for campaign in campaigns if campaign.get("status") == "active"]
    metrics["campaigns"] = campaigns
    metrics["filters"] = filters
    return metrics


def record_simulation_event(
    conn,
    campaign_id,
    event_type,
    target_id=None,
    channel=None,
    delivery_status=None,
    metadata=None,
    occurred_at=None,
    delivery_job_id=None,
    delivery_attempt_id=None,
    tracking_token_id=None,
    provider_reference_id=None,
    provider=None,
    provider_event_id=None,
    error_message=None,
    retry_count=0,
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
            delivery_job_id, delivery_attempt_id, tracking_token_id,
            provider_reference_id, provider, provider_event_id, error_message,
            retry_count, occurred_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            target_id,
            event_channel,
            normalized_event,
            event_status,
            delivery_job_id,
            delivery_attempt_id,
            tracking_token_id,
            provider_reference_id,
            _normalize_text(provider),
            _normalize_text(provider_event_id),
            _normalize_text(error_message),
            int(retry_count or 0),
            timestamp,
            metadata_json,
        ),
    )
    event_id = cursor.lastrowid

    if target_id is not None:
        assignments = ["updated_at = ?"]
        values = [timestamp]
        timestamp_column = event_config.get("timestamp_column")
        if timestamp_column:
            assignments.insert(0, "{} = ?".format(timestamp_column))
            values.insert(0, timestamp)
        target_column = event_config.get("target_column")
        if target_column == "delivery_status":
            assignments.insert(0, "delivery_status = ?")
            values.insert(0, event_status or "delivered")
        elif target_column:
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
                delivery_job_id,
                delivery_attempt_id,
                tracking_token_id,
                provider_reference_id,
                provider,
                provider_event_id,
                error_message,
                retry_count,
                occurred_at,
                metadata,
                created_at
            FROM simulation_events
            WHERE id = ?
            """,
            (event_id,),
        )
    )


def list_delivery_provider_settings(conn, channel=None):
    """Return delivery provider settings without secret material."""
    params = []
    filters = []
    if channel is not None:
        normalized_channel = (_normalize_text(channel) or "").lower()
        if normalized_channel not in VALID_SIMULATION_CHANNELS:
            raise ValueError("Delivery provider channel must be one of: {}".format(", ".join(sorted(VALID_SIMULATION_CHANNELS))))
        filters.append("channel = ?")
        params.append(normalized_channel)
    where = "WHERE {}".format(" AND ".join(filters)) if filters else ""
    cursor = conn.execute(
        f"""
        SELECT
            id,
            channel,
            provider_key,
            provider_name,
            provider_type,
            enabled,
            settings_json,
            required_settings_json,
            secret_placeholder,
            last_error_message,
            created_at,
            updated_at
        FROM simulation_channel_providers
        {where}
        ORDER BY channel ASC, provider_type ASC, provider_name ASC
        """,
        params,
    )
    return [_delivery_provider_response(row) for row in _rows_to_dicts(cursor)]


def _provider_for_channel(conn, channel, provider_ids=None, mode="dry_run"):
    provider_id = None
    if isinstance(provider_ids, dict):
        provider_id = provider_ids.get(channel)
    elif provider_ids:
        provider_id = provider_ids

    if provider_id:
        provider = get_delivery_provider_settings(conn, provider_id)
        if not provider:
            raise ValueError("Unknown delivery provider config id: {}".format(provider_id))
        if provider["channel"] != channel:
            raise ValueError("Provider '{}' is not configured for {} delivery.".format(provider["provider_name"], channel))
        return provider

    providers = list_delivery_provider_settings(conn, channel=channel)
    if mode == "dry_run":
        for provider in providers:
            if provider["provider_type"] == "dry_run" and provider["enabled"]:
                return provider
    for provider in providers:
        if provider["enabled"]:
            return provider
    raise ValueError("No enabled {} delivery provider is configured.".format(channel))


def _latest_campaign_draft(conn, campaign_id):
    return _row_to_dict(
        conn.execute(
            """
            SELECT email_subject, email_body, sms_body, voice_script, landing_text,
                   training_text, channels, metadata
            FROM ai_campaign_drafts
            WHERE campaign_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (campaign_id,),
        )
    )


def _message_for_channel(campaign, draft, channel):
    draft = draft or {}
    training_text = _normalize_text(draft.get("training_text")) or _normalize_text(campaign.get("training_url"))
    if channel == "email":
        subject = _normalize_text(draft.get("email_subject")) or "Authorized security awareness training"
        body = _normalize_text(draft.get("email_body")) or (
            "This is an authorized security awareness training simulation for {}.".format(campaign["name"])
        )
    elif channel == "sms":
        subject = None
        body = _normalize_text(draft.get("sms_body")) or (
            "Authorized security awareness training simulation: {}".format(campaign["name"])
        )
    else:
        subject = None
        body = _normalize_text(draft.get("voice_script")) or (
            "This is an authorized security awareness training simulation call for {}.".format(campaign["name"])
        )
    return {
        "channel": channel,
        "subject": subject,
        "body": body,
        "content": {
            "campaign_name": campaign["name"],
            "landing_url": campaign.get("landing_url"),
            "training_url": campaign.get("training_url"),
            "training_text": training_text,
        },
    }


def build_delivery_preview(conn, campaign_id, provider_ids=None, mode="dry_run"):
    """Build a delivery preview from active campaign targets without creating records."""
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))

    targets = [target for target in list_targets(conn, campaign_id) if target["active"]]
    draft = _latest_campaign_draft(conn, campaign_id)
    channels = sorted({target["channel"] for target in targets})
    providers = {channel: _provider_for_channel(conn, channel, provider_ids, mode) for channel in channels}
    messages = {channel: _message_for_channel(campaign, draft, channel) for channel in channels}
    return {
        "campaign": campaign,
        "targets": targets,
        "providers": providers,
        "messages": messages,
        "total_targets": len(targets),
        "total_attempts": len(targets),
        "mode": mode,
    }


def _create_message_artifacts(conn, campaign_id, job_id, messages):
    artifacts = {}
    now = _utc_now()
    for channel, message in messages.items():
        content = dict(message.get("content") or {})
        content["channel"] = channel
        content_hash = _content_hash(
            {
                "subject": message.get("subject"),
                "body": message.get("body"),
                "content": content,
            }
        )
        existing = _row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM simulation_message_artifacts
                WHERE delivery_job_id = ? AND channel = ? AND content_hash = ?
                """,
                (job_id, channel, content_hash),
            )
        )
        if existing:
            artifacts[channel] = _message_artifact_response(existing)
            continue
        cursor = conn.execute(
            """
            INSERT INTO simulation_message_artifacts (
                campaign_id, delivery_job_id, channel, artifact_type, subject,
                body, content_json, content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, 'message', ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                job_id,
                channel,
                message.get("subject"),
                message.get("body"),
                _safe_json_dumps(content),
                content_hash,
                now,
                now,
            ),
        )
        artifacts[channel] = get_message_artifact(conn, cursor.lastrowid)
    return artifacts


def _token_value():
    return secrets.token_urlsafe(24)


def _ensure_tracking_tokens(conn, campaign_id, job_id, target, artifact_id):
    tokens = []
    now = _utc_now()
    token_types = ("open", "link", "attachment")
    for token_type in token_types:
        existing = _row_to_dict(
            conn.execute(
                """
                SELECT *
                FROM simulation_tracking_tokens
                WHERE campaign_id = ? AND target_id = ? AND delivery_job_id = ?
                  AND message_artifact_id = ? AND token_type = ?
                """,
                (campaign_id, target["id"], job_id, artifact_id, token_type),
            )
        )
        if existing:
            tokens.append(_tracking_token_response(existing))
            continue
        destination_url = None
        if token_type == "link":
            campaign = get_campaign(conn, campaign_id)
            destination_url = campaign.get("training_url") or campaign.get("landing_url")
        cursor = conn.execute(
            """
            INSERT INTO simulation_tracking_tokens (
                campaign_id, target_id, delivery_job_id, message_artifact_id,
                channel, token, token_type, destination_url, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                target["id"],
                job_id,
                artifact_id,
                target["channel"],
                _token_value(),
                token_type,
                destination_url,
                now,
                now,
            ),
        )
        tokens.append(get_tracking_token(conn, cursor.lastrowid))
    return tokens


def create_delivery_job_from_campaign(
    conn,
    campaign_id,
    provider_ids=None,
    mode="dry_run",
    requested_by=None,
    max_retries=0,
):
    """Create a delivery job, artifacts, tracking tokens, and per-target attempts."""
    preview = build_delivery_preview(conn, campaign_id, provider_ids=provider_ids, mode=mode)
    if not preview["targets"]:
        raise ValueError("Campaign has no active targets to deliver.")

    now = _utc_now()
    provider_snapshot = {
        channel: {
            "id": provider["id"],
            "provider_key": provider["provider_key"],
            "provider_name": provider["provider_name"],
            "provider_type": provider["provider_type"],
            "enabled": provider["enabled"],
        }
        for channel, provider in preview["providers"].items()
    }
    cursor = conn.execute(
        """
        INSERT INTO simulation_delivery_jobs (
            campaign_id, status, mode, requested_by, provider_snapshot,
            total_targets, total_attempts, queued_count, queued_at, created_at, updated_at
        )
        VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            _normalize_text(mode) or "dry_run",
            _normalize_text(requested_by),
            _safe_json_dumps(provider_snapshot),
            preview["total_targets"],
            preview["total_attempts"],
            preview["total_attempts"],
            now,
            now,
            now,
        ),
    )
    job_id = cursor.lastrowid
    artifacts = _create_message_artifacts(conn, campaign_id, job_id, preview["messages"])

    for target in preview["targets"]:
        channel = target["channel"]
        artifact = artifacts[channel]
        provider = preview["providers"][channel]
        _ensure_tracking_tokens(conn, campaign_id, job_id, target, artifact["id"])
        conn.execute(
            """
            INSERT OR IGNORE INTO simulation_delivery_attempts (
                delivery_job_id, campaign_id, target_id, message_artifact_id,
                provider_id, channel, status, max_retries, queued_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (
                job_id,
                campaign_id,
                target["id"],
                artifact["id"],
                provider["id"],
                channel,
                int(max_retries or 0),
                now,
                now,
                now,
            ),
        )
        record_simulation_event(
            conn,
            campaign_id,
            "queued",
            target_id=target["id"],
            channel=channel,
            delivery_job_id=job_id,
            provider_reference_id=provider["id"],
            metadata={"delivery_job_id": job_id, "provider_key": provider["provider_key"]},
        )

    conn.commit()
    return get_delivery_job_status(conn, job_id)


def get_message_artifact(conn, artifact_id):
    row = _row_to_dict(conn.execute("SELECT * FROM simulation_message_artifacts WHERE id = ?", (artifact_id,)))
    return _message_artifact_response(row) if row else None


def get_tracking_token(conn, token_id):
    row = _row_to_dict(conn.execute("SELECT * FROM simulation_tracking_tokens WHERE id = ?", (token_id,)))
    return _tracking_token_response(row) if row else None


def get_tracking_token_by_value(conn, token):
    row = _row_to_dict(
        conn.execute(
            "SELECT * FROM simulation_tracking_tokens WHERE token = ?",
            (_normalize_text(token),),
        )
    )
    return _tracking_token_response(row) if row else None


def _tracking_event_type(token_type):
    event_types = {
        "open": "opened",
        "link": "link_click",
        "attachment": "attachment_open",
    }
    return event_types.get((_normalize_text(token_type) or "").lower())


def _tracking_attempt(conn, token):
    return _row_to_dict(
        conn.execute(
            """
            SELECT id, provider_id, provider, provider_message_id
            FROM simulation_delivery_attempts
            WHERE delivery_job_id = ? AND target_id = ? AND channel = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (token.get("delivery_job_id"), token.get("target_id"), token.get("channel")),
        )
    )


def record_tracking_token_event(conn, token_value, token_type=None, metadata=None):
    """Record a public tracking-token event and update token counters."""
    token = get_tracking_token_by_value(conn, token_value)
    if not token:
        raise ValueError("Unknown simulation tracking token.")

    expected_type = (_normalize_text(token_type) or token["token_type"]).lower()
    actual_type = (_normalize_text(token["token_type"]) or "").lower()
    if expected_type != actual_type:
        raise ValueError("Tracking token is not valid for {} events.".format(expected_type))

    event_type = _tracking_event_type(actual_type)
    if not event_type:
        raise ValueError("Unsupported simulation tracking token type: {}".format(actual_type))

    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_tracking_tokens
        SET first_seen_at = COALESCE(first_seen_at, ?),
            last_seen_at = ?,
            event_count = event_count + 1,
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, now, token["id"]),
    )
    attempt = _tracking_attempt(conn, token) or {}
    event_metadata = dict(metadata or {})
    event_metadata.update({
        "source": event_metadata.get("source") or "simulation_tracking",
        "token_type": actual_type,
    })
    event = record_simulation_event(
        conn,
        token["campaign_id"],
        event_type,
        target_id=token["target_id"],
        channel=token["channel"],
        occurred_at=now,
        delivery_job_id=token.get("delivery_job_id"),
        delivery_attempt_id=attempt.get("id"),
        tracking_token_id=token["id"],
        provider_reference_id=attempt.get("provider_id"),
        provider=attempt.get("provider"),
        provider_event_id=attempt.get("provider_message_id"),
        metadata=event_metadata,
    )
    return {
        "token": get_tracking_token(conn, token["id"]),
        "event": event,
    }


def get_delivery_job(conn, job_id):
    row = _row_to_dict(conn.execute("SELECT * FROM simulation_delivery_jobs WHERE id = ?", (job_id,)))
    return _delivery_job_response(row)


def list_delivery_jobs(conn, campaign_id=None, limit=5):
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE campaign_id = ?"
        params.append(campaign_id)
    params.append(int(limit or 5))
    rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT *
            FROM simulation_delivery_jobs
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        )
    )
    return [_delivery_job_response(row) for row in rows]


def list_delivery_attempts(conn, job_id):
    rows = _rows_to_dicts(
        conn.execute(
            """
            SELECT
                a.*,
                t.name AS target_name,
                t.display_name AS target_display_name,
                t.email AS target_email,
                t.phone AS target_phone,
                p.provider_key,
                p.provider_name,
                p.provider_type
            FROM simulation_delivery_attempts a
            JOIN simulation_targets t ON t.id = a.target_id
            LEFT JOIN simulation_channel_providers p ON p.id = a.provider_id
            WHERE a.delivery_job_id = ?
            ORDER BY a.id ASC
            """,
            (job_id,),
        )
    )
    return [_delivery_attempt_response(row) for row in rows]


def list_tracking_tokens_for_job(conn, job_id):
    rows = _rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM simulation_tracking_tokens
            WHERE delivery_job_id = ?
            ORDER BY target_id ASC, token_type ASC
            """,
            (job_id,),
        )
    )
    return [_tracking_token_response(row) for row in rows]


def _refresh_delivery_job_counts(conn, job_id):
    now = _utc_now()
    counts = _row_to_dict(
        conn.execute(
            """
            SELECT
                COUNT(*) AS total_attempts,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_count,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent_count,
                SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(retry_count) AS retry_count
            FROM simulation_delivery_attempts
            WHERE delivery_job_id = ?
            """,
            (job_id,),
        )
    )
    total = int(counts.get("total_attempts") or 0)
    failed = int(counts.get("failed_count") or 0)
    queued = int(counts.get("queued_count") or 0)
    delivered = int(counts.get("delivered_count") or 0)
    sent = int(counts.get("sent_count") or 0)
    status = "queued" if queued == total else "completed"
    if failed and queued == 0 and delivered + sent + failed == total:
        status = "completed_with_errors"
    completed_at = now if status.startswith("completed") else None
    conn.execute(
        """
        UPDATE simulation_delivery_jobs
        SET total_attempts = ?, queued_count = ?, sent_count = ?,
            delivered_count = ?, failed_count = ?, retry_count = ?,
            status = ?, completed_at = COALESCE(completed_at, ?), updated_at = ?
        WHERE id = ?
        """,
        (
            total,
            queued,
            sent,
            delivered,
            failed,
            int(counts.get("retry_count") or 0),
            status,
            completed_at,
            now,
            job_id,
        ),
    )
    conn.commit()


def _attempt_request(conn, attempt):
    from core.delivery_adapters import DeliveryAttemptRequest, DeliveryMessage, DeliveryRecipient

    artifact = get_message_artifact(conn, attempt["message_artifact_id"])
    target = get_target(conn, attempt["target_id"])
    message = DeliveryMessage(
        channel=attempt["channel"],
        subject=artifact.get("subject") if artifact else None,
        body=artifact.get("body") if artifact else None,
        content=artifact.get("content") if artifact else {},
    )
    recipient = DeliveryRecipient(
        target_id=target["id"],
        name=target.get("display_name") or target["name"],
        email=target.get("email"),
        phone=target.get("phone"),
    )
    return DeliveryAttemptRequest(
        campaign_id=attempt["campaign_id"],
        target_id=attempt["target_id"],
        channel=attempt["channel"],
        message=message,
        recipient=recipient,
        delivery_job_id=attempt["delivery_job_id"],
        attempt_id=attempt["id"],
        metadata={"retry_count": attempt.get("retry_count") or 0},
    )


def run_delivery_job(conn, job_id):
    """Process queued/retryable delivery attempts while skipping completed attempts."""
    from core.delivery_adapters import DeliveryProviderError, send_with_provider_settings

    job = get_delivery_job(conn, job_id)
    if not job:
        raise ValueError("Unknown delivery job id: {}".format(job_id))

    now = _utc_now()
    conn.execute(
        """
        UPDATE simulation_delivery_jobs
        SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
        WHERE id = ?
        """,
        (now, now, job_id),
    )
    conn.commit()

    processed = []
    for attempt in list_delivery_attempts(conn, job_id):
        if attempt["status"] in {"sent", "delivered"}:
            continue
        if attempt["status"] == "failed" and int(attempt.get("retry_count") or 0) >= int(attempt.get("max_retries") or 0):
            continue

        provider = get_delivery_provider_settings(conn, attempt["provider_id"])
        request = _attempt_request(conn, attempt)
        retry_count = int(attempt.get("retry_count") or 0)
        if attempt["status"] == "failed":
            retry_count += 1
        try:
            result = send_with_provider_settings(provider, request)
            timestamp = _utc_now()
            status = result.status
            conn.execute(
                """
                UPDATE simulation_delivery_attempts
                SET status = ?, provider = ?, provider_message_id = ?,
                    provider_response = ?, error_message = NULL, retry_count = ?,
                    sent_at = COALESCE(sent_at, ?),
                    delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END,
                    failed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    result.provider,
                    result.provider_message_id,
                    _safe_json_dumps(result.provider_response),
                    retry_count,
                    timestamp,
                    status,
                    timestamp,
                    timestamp,
                    attempt["id"],
                ),
            )
            event = record_simulation_event(
                conn,
                attempt["campaign_id"],
                result.event_type,
                target_id=attempt["target_id"],
                channel=attempt["channel"],
                delivery_status=status,
                delivery_job_id=job_id,
                delivery_attempt_id=attempt["id"],
                provider_reference_id=attempt["provider_id"],
                provider=result.provider,
                provider_event_id=result.provider_message_id,
                retry_count=retry_count,
                metadata=result.event_metadata,
            )
            processed.append({"attempt_id": attempt["id"], "status": status, "event": event})
        except DeliveryProviderError as exc:
            timestamp = _utc_now()
            error_message = str(exc)
            conn.execute(
                """
                UPDATE simulation_delivery_attempts
                SET status = 'failed', error_message = ?, retry_count = ?,
                    failed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (error_message, retry_count, timestamp, timestamp, attempt["id"]),
            )
            event = record_simulation_event(
                conn,
                attempt["campaign_id"],
                "failed",
                target_id=attempt["target_id"],
                channel=attempt["channel"],
                delivery_status="failed",
                delivery_job_id=job_id,
                delivery_attempt_id=attempt["id"],
                provider_reference_id=attempt["provider_id"],
                error_message=error_message,
                retry_count=retry_count,
                metadata={"error_message": error_message},
            )
            processed.append({"attempt_id": attempt["id"], "status": "failed", "event": event})

    _refresh_delivery_job_counts(conn, job_id)
    status = get_delivery_job_status(conn, job_id)
    status["processed_attempts"] = processed
    return status


def get_delivery_job_status(conn, job_id):
    job = get_delivery_job(conn, job_id)
    if not job:
        raise ValueError("Unknown delivery job id: {}".format(job_id))
    return {
        "job": job,
        "attempts": list_delivery_attempts(conn, job_id),
        "tracking_tokens": list_tracking_tokens_for_job(conn, job_id),
    }


def get_delivery_provider_settings(conn, provider_id):
    provider = _row_to_dict(
        conn.execute(
            """
            SELECT
                id,
                channel,
                provider_key,
                provider_name,
                provider_type,
                enabled,
                settings_json,
                required_settings_json,
                secret_placeholder,
                last_error_message,
                created_at,
                updated_at
            FROM simulation_channel_providers
            WHERE id = ?
            """,
            (provider_id,),
        )
    )
    return _delivery_provider_response(provider) if provider else None


def get_delivery_provider_by_key(conn, channel, provider_key):
    normalized_channel = (_normalize_text(channel) or "").lower()
    if normalized_channel not in VALID_SIMULATION_CHANNELS:
        raise ValueError("Delivery provider channel must be one of: {}".format(", ".join(sorted(VALID_SIMULATION_CHANNELS))))
    provider = _row_to_dict(
        conn.execute(
            """
            SELECT
                id,
                channel,
                provider_key,
                provider_name,
                provider_type,
                enabled,
                settings_json,
                required_settings_json,
                secret_placeholder,
                last_error_message,
                created_at,
                updated_at
            FROM simulation_channel_providers
            WHERE channel = ? AND provider_key = ?
            """,
            (normalized_channel, _normalize_text(provider_key)),
        )
    )
    return _delivery_provider_response(provider) if provider else None


def record_provider_webhook_event(conn, channel, provider_key, payload):
    """Record a future provider webhook event without requiring provider credentials."""
    provider = get_delivery_provider_by_key(conn, channel, provider_key)
    if not provider:
        raise ValueError("Unknown simulation delivery provider: {}/{}".format(channel, provider_key))

    payload = payload or {}
    token_value = _normalize_text(payload.get("tracking_token") or payload.get("token"))
    token = get_tracking_token_by_value(conn, token_value) if token_value else None
    event_type = _normalize_text(
        payload.get("event_type") or payload.get("event") or payload.get("type")
    )
    if not event_type and token:
        event_type = _tracking_event_type(token["token_type"])
    if not event_type:
        raise ValueError("Webhook payload must include an event_type or tracking token.")

    campaign_id = payload.get("campaign_id") or (token or {}).get("campaign_id")
    target_id = payload.get("target_id") or (token or {}).get("target_id")
    delivery_job_id = payload.get("delivery_job_id") or (token or {}).get("delivery_job_id")
    tracking_token_id = (token or {}).get("id")
    attempt = None
    provider_message_id = _normalize_text(
        payload.get("provider_event_id") or payload.get("provider_message_id") or payload.get("message_id")
    )
    if provider_message_id:
        attempt = _row_to_dict(
            conn.execute(
                """
                SELECT id, delivery_job_id, campaign_id, target_id, channel
                FROM simulation_delivery_attempts
                WHERE provider_message_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (provider_message_id,),
            )
        )
    if not attempt and token:
        attempt = _tracking_attempt(conn, token)
    if attempt:
        campaign_id = campaign_id or attempt.get("campaign_id")
        target_id = target_id or attempt.get("target_id")
        delivery_job_id = delivery_job_id or attempt.get("delivery_job_id")

    if tracking_token_id:
        now = _utc_now()
        conn.execute(
            """
            UPDATE simulation_tracking_tokens
            SET first_seen_at = COALESCE(first_seen_at, ?),
                last_seen_at = ?,
                event_count = event_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, now, tracking_token_id),
        )

    metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    metadata.update({
        "source": "provider_webhook",
        "provider_key": provider["provider_key"],
        "raw_event_type": event_type,
    })
    event = record_simulation_event(
        conn,
        int(campaign_id),
        event_type,
        target_id=int(target_id) if target_id is not None else None,
        channel=provider["channel"],
        delivery_status=payload.get("delivery_status"),
        delivery_job_id=int(delivery_job_id) if delivery_job_id is not None else None,
        delivery_attempt_id=(attempt or {}).get("id"),
        tracking_token_id=tracking_token_id,
        provider_reference_id=provider["id"],
        provider=provider["provider_key"],
        provider_event_id=provider_message_id,
        error_message=payload.get("error_message"),
        retry_count=int(payload.get("retry_count") or 0),
        metadata=metadata,
    )
    return {
        "provider": provider,
        "event": event,
        "tracking_token": get_tracking_token(conn, tracking_token_id) if tracking_token_id else None,
    }


def update_delivery_provider_settings(
    conn,
    provider_id,
    provider_name=None,
    enabled=None,
    settings=None,
    secret=None,
    last_error_message=None,
):
    """Update UI-managed delivery provider settings without storing secret text."""
    existing = _row_to_dict(
        conn.execute(
            "SELECT * FROM simulation_channel_providers WHERE id = ?",
            (provider_id,),
        )
    )
    if not existing:
        raise ValueError("Unknown delivery provider config id: {}".format(provider_id))

    existing_settings = _json_dict(existing.get("settings_json"))
    if settings is not None:
        if not isinstance(settings, dict):
            raise ValueError("Delivery provider settings must be a JSON object.")
        existing_settings.update({
            str(key): _normalize_text(value)
            for key, value in settings.items()
            if _normalize_text(key)
        })

    now = _utc_now()
    updated = {
        "provider_name": _normalize_text(provider_name) or existing["provider_name"],
        "enabled": 1 if bool(enabled) else 0 if enabled is not None else existing["enabled"],
        "settings_json": _safe_json_dumps(existing_settings),
        "secret_placeholder": existing["secret_placeholder"],
        "last_error_message": _normalize_text(last_error_message),
        "updated_at": now,
    }
    if secret:
        updated["secret_placeholder"] = "configured"

    conn.execute(
        """
        UPDATE simulation_channel_providers
        SET
            provider_name = ?,
            enabled = ?,
            settings_json = ?,
            secret_placeholder = ?,
            last_error_message = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            updated["provider_name"],
            updated["enabled"],
            updated["settings_json"],
            updated["secret_placeholder"],
            updated["last_error_message"],
            updated["updated_at"],
            provider_id,
        ),
    )
    conn.commit()
    return get_delivery_provider_settings(conn, provider_id)


def list_directory_provider_settings(conn, provider_type=None):
    """Return directory provider settings without raw OAuth secret material."""
    params = []
    filters = []
    if provider_type is not None:
        normalized_type = (_normalize_text(provider_type) or "").lower()
        filters.append("provider_type = ?")
        params.append(normalized_type)
    where = "WHERE {}".format(" AND ".join(filters)) if filters else ""
    cursor = conn.execute(
        f"""
        SELECT
            id,
            name,
            provider_type,
            tenant_id,
            tenant_name,
            authority_url,
            client_id,
            enabled,
            consent_status,
            consented_scopes_json,
            selected_groups_json,
            field_mapping_json,
            settings_json,
            secret_reference,
            secret_placeholder,
            last_sync_status,
            last_sync_job_id,
            last_sync_at,
            last_error_message,
            created_at,
            updated_at
        FROM directory_providers
        {where}
        ORDER BY name ASC, id ASC
        """,
        params,
    )
    return [_directory_provider_response(row) for row in _rows_to_dicts(cursor)]


def get_directory_provider_settings(conn, provider_id):
    provider = _row_to_dict(
        conn.execute(
            """
            SELECT
                id,
                name,
                provider_type,
                tenant_id,
                tenant_name,
                authority_url,
                client_id,
                enabled,
                consent_status,
                consented_scopes_json,
                selected_groups_json,
                field_mapping_json,
                settings_json,
                secret_reference,
                secret_placeholder,
                last_sync_status,
                last_sync_job_id,
                last_sync_at,
                last_error_message,
                created_at,
                updated_at
            FROM directory_providers
            WHERE id = ?
            """,
            (provider_id,),
        )
    )
    return _directory_provider_response(provider) if provider else None


def create_directory_provider_settings(
    conn,
    name,
    provider_type="mock_entra",
    tenant_id=None,
    tenant_name=None,
    authority_url=None,
    client_id=None,
    enabled=False,
    consent_status="not_configured",
    consented_scopes=None,
    selected_groups=None,
    field_mapping=None,
    settings=None,
    secret_reference=None,
    secret=None,
):
    """Create UI-managed directory provider settings without storing raw secrets."""
    normalized_name = _normalize_text(name)
    if not normalized_name:
        raise ValueError("Directory provider name is required.")
    if field_mapping is not None and not isinstance(field_mapping, dict):
        raise ValueError("Directory field mapping must be a JSON object.")
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("Directory provider settings must be a JSON object.")

    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO directory_providers (
            name, provider_type, tenant_id, tenant_name, authority_url,
            client_id, enabled, consent_status, consented_scopes_json,
            selected_groups_json, field_mapping_json, settings_json,
            secret_reference, secret_placeholder, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalized_name,
            (_normalize_text(provider_type) or "mock_entra").lower(),
            _normalize_text(tenant_id),
            _normalize_text(tenant_name),
            _normalize_text(authority_url),
            _normalize_text(client_id),
            1 if bool(enabled) else 0,
            (_normalize_text(consent_status) or "not_configured").lower(),
            json.dumps(list(consented_scopes or []), sort_keys=True),
            json.dumps(list(selected_groups or []), sort_keys=True),
            _safe_json_dumps(field_mapping),
            _safe_json_dumps(settings),
            _normalize_text(secret_reference),
            "configured" if secret else "not-configured",
            now,
            now,
        ),
    )
    conn.commit()
    return get_directory_provider_settings(conn, cursor.lastrowid)


def update_directory_provider_settings(
    conn,
    provider_id,
    name=None,
    provider_type=None,
    tenant_id=None,
    tenant_name=None,
    authority_url=None,
    client_id=None,
    enabled=None,
    consent_status=None,
    consented_scopes=None,
    selected_groups=None,
    field_mapping=None,
    settings=None,
    secret_reference=None,
    secret=None,
    last_error_message=None,
):
    """Update directory provider settings while preserving write-only secrets."""
    existing = _row_to_dict(
        conn.execute(
            "SELECT * FROM directory_providers WHERE id = ?",
            (provider_id,),
        )
    )
    if not existing:
        raise ValueError("Unknown directory provider config id: {}".format(provider_id))
    if field_mapping is not None and not isinstance(field_mapping, dict):
        raise ValueError("Directory field mapping must be a JSON object.")
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("Directory provider settings must be a JSON object.")

    existing_settings = _json_dict(existing.get("settings_json"))
    if settings is not None:
        existing_settings.update({
            str(key): _normalize_text(value)
            for key, value in settings.items()
            if _normalize_text(key)
        })

    now = _utc_now()
    updated = {
        "name": _normalize_text(name) or existing["name"],
        "provider_type": (_normalize_text(provider_type) or existing["provider_type"]).lower(),
        "tenant_id": _normalize_text(tenant_id) if tenant_id is not None else existing["tenant_id"],
        "tenant_name": _normalize_text(tenant_name) if tenant_name is not None else existing["tenant_name"],
        "authority_url": _normalize_text(authority_url) if authority_url is not None else existing["authority_url"],
        "client_id": _normalize_text(client_id) if client_id is not None else existing["client_id"],
        "enabled": 1 if bool(enabled) else 0 if enabled is not None else existing["enabled"],
        "consent_status": (_normalize_text(consent_status) or existing["consent_status"]).lower(),
        "consented_scopes_json": json.dumps(
            list(consented_scopes) if consented_scopes is not None else _json_list(existing["consented_scopes_json"]),
            sort_keys=True,
        ),
        "selected_groups_json": json.dumps(
            list(selected_groups) if selected_groups is not None else _json_list(existing["selected_groups_json"]),
            sort_keys=True,
        ),
        "field_mapping_json": _safe_json_dumps(
            field_mapping if field_mapping is not None else _json_dict(existing["field_mapping_json"])
        ),
        "settings_json": _safe_json_dumps(existing_settings),
        "secret_reference": _normalize_text(secret_reference) if secret_reference is not None else existing["secret_reference"],
        "secret_placeholder": existing["secret_placeholder"],
        "last_error_message": _normalize_text(last_error_message),
        "updated_at": now,
    }
    if secret:
        updated["secret_placeholder"] = "configured"

    conn.execute(
        """
        UPDATE directory_providers
        SET
            name = ?,
            provider_type = ?,
            tenant_id = ?,
            tenant_name = ?,
            authority_url = ?,
            client_id = ?,
            enabled = ?,
            consent_status = ?,
            consented_scopes_json = ?,
            selected_groups_json = ?,
            field_mapping_json = ?,
            settings_json = ?,
            secret_reference = ?,
            secret_placeholder = ?,
            last_error_message = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            updated["name"],
            updated["provider_type"],
            updated["tenant_id"],
            updated["tenant_name"],
            updated["authority_url"],
            updated["client_id"],
            updated["enabled"],
            updated["consent_status"],
            updated["consented_scopes_json"],
            updated["selected_groups_json"],
            updated["field_mapping_json"],
            updated["settings_json"],
            updated["secret_reference"],
            updated["secret_placeholder"],
            updated["last_error_message"],
            updated["updated_at"],
            provider_id,
        ),
    )
    conn.commit()
    return get_directory_provider_settings(conn, provider_id)


def _directory_provider_or_error(conn, provider_id):
    provider = get_directory_provider_settings(conn, provider_id)
    if not provider:
        raise ValueError("Unknown directory provider config id: {}".format(provider_id))
    return provider


def list_directory_groups(conn, provider_id):
    """List groups through the connector selected by UI-managed provider type."""
    from core.directory_connectors import list_groups_with_provider_settings

    return list_groups_with_provider_settings(_directory_provider_or_error(conn, provider_id))


def preview_directory_users(conn, provider_id, group_ids=None):
    """Preview directory users through the connector selected by UI-managed settings."""
    from core.directory_connectors import preview_users_with_provider_settings

    return preview_users_with_provider_settings(_directory_provider_or_error(conn, provider_id), group_ids=group_ids)


def sync_directory_staged_users(conn, provider_id, group_ids=None):
    """Return staged user candidates without importing them into campaigns."""
    from core.directory_connectors import sync_staged_users_with_provider_settings

    return sync_staged_users_with_provider_settings(_directory_provider_or_error(conn, provider_id), group_ids=group_ids)


def map_directory_user_to_target(conn, provider_id, user):
    """Map a connector user into the existing simulation target payload shape."""
    from core.directory_connectors import map_user_to_target_with_provider_settings

    return map_user_to_target_with_provider_settings(_directory_provider_or_error(conn, provider_id), user)


def _directory_default_campaign_id(conn):
    campaign = _row_to_dict(
        conn.execute(
            "SELECT id FROM simulation_campaigns WHERE slug = ?",
            (SIMULATION_DEMO_SLUG,),
        )
    )
    if campaign:
        return campaign["id"]
    first = _row_to_dict(conn.execute("SELECT id FROM simulation_campaigns ORDER BY id ASC LIMIT 1"))
    if first:
        return first["id"]
    raise ValueError("Directory sync import requires at least one simulation campaign.")


def _create_directory_sync_job(conn, provider_id, job_type, selected_groups=None, requested_by=None):
    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO directory_sync_jobs (
            provider_id, job_type, status, selected_groups_json, requested_by,
            started_at, created_at, updated_at
        )
        VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
        """,
        (
            provider_id,
            job_type,
            json.dumps(list(selected_groups or []), sort_keys=True),
            _normalize_text(requested_by),
            now,
            now,
            now,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _record_directory_sync_audit_event(
    conn,
    provider_id,
    sync_job_id,
    event_type,
    message,
    severity="info",
    actor=None,
    metadata=None,
):
    conn.execute(
        """
        INSERT INTO directory_sync_audit_events (
            provider_id, sync_job_id, event_type, severity, actor, message,
            metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider_id,
            sync_job_id,
            event_type,
            severity,
            _normalize_text(actor),
            _normalize_text(message),
            _safe_json_dumps(metadata),
            _utc_now(),
        ),
    )
    conn.commit()


def _update_directory_sync_job(conn, job_id, status, **counts):
    now = _utc_now()
    existing = _row_to_dict(conn.execute("SELECT * FROM directory_sync_jobs WHERE id = ?", (job_id,)))
    if not existing:
        raise ValueError("Unknown directory sync job id: {}".format(job_id))
    validation_errors = counts.get("validation_errors")
    conn.execute(
        """
        UPDATE directory_sync_jobs
        SET status = ?, total_groups = ?, total_users = ?, staged_count = ?,
            imported_count = ?, skipped_count = ?, invalid_count = ?,
            duplicate_count = ?, validation_errors_json = ?, completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            int(counts.get("total_groups", existing["total_groups"]) or 0),
            int(counts.get("total_users", existing["total_users"]) or 0),
            int(counts.get("staged_count", existing["staged_count"]) or 0),
            int(counts.get("imported_count", existing["imported_count"]) or 0),
            int(counts.get("skipped_count", existing["skipped_count"]) or 0),
            int(counts.get("invalid_count", existing["invalid_count"]) or 0),
            int(counts.get("duplicate_count", existing["duplicate_count"]) or 0),
            json.dumps(list(validation_errors or _json_list(existing["validation_errors_json"])), sort_keys=True),
            now,
            now,
            job_id,
        ),
    )
    conn.commit()


def _update_directory_provider_sync_state(conn, provider_id, job_id, status, error_message=None):
    now = _utc_now()
    conn.execute(
        """
        UPDATE directory_providers
        SET last_sync_status = ?, last_sync_job_id = ?, last_sync_at = ?,
            last_error_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            job_id,
            now,
            _normalize_text(error_message),
            now,
            provider_id,
        ),
    )
    conn.commit()


def _stage_directory_sync_users(conn, provider, job_id, result):
    validation_errors = []
    staged_count = 0
    invalid_count = 0
    for user in result.users:
        user_errors = []
        target_payload = {}
        if not _normalize_text(user.external_user_id):
            user_errors.append("Directory user is missing an external user id.")
        try:
            target_payload = map_directory_user_to_target(conn, provider["id"], user)
            _normalize_target_payload(target_payload, source="directory")
        except ValueError as exc:
            user_errors.append(str(exc))
        status = "invalid" if user_errors else "valid"
        invalid_count += 1 if user_errors else 0
        validation_errors.extend(
            {
                "external_user_id": user.external_user_id,
                "message": error,
            }
            for error in user_errors
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO staged_directory_users (
                provider_id, sync_job_id, external_user_id, user_principal_name,
                mail, display_name, given_name, surname, job_title, department,
                office_location, mobile_phone, business_phones_json, manager,
                groups_json, source_group_ids_json, active, validation_status,
                validation_errors_json, target_payload_json, imported_target_id,
                staged_at, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                provider["id"],
                job_id,
                user.external_user_id,
                user.user_principal_name,
                user.mail,
                user.display_name,
                user.given_name,
                user.surname,
                user.job_title,
                user.department,
                user.office_location,
                user.mobile_phone,
                json.dumps(list(user.business_phones), sort_keys=True),
                user.manager,
                json.dumps(list(user.groups), sort_keys=True),
                json.dumps(list(user.source_group_ids), sort_keys=True),
                1 if user.active else 0,
                status,
                json.dumps(user_errors, sort_keys=True),
                _safe_json_dumps(target_payload),
                _utc_now(),
            ),
        )
        staged_count += 1
    conn.commit()
    return {
        "staged_count": staged_count,
        "invalid_count": invalid_count,
        "validation_errors": validation_errors,
    }


def _target_contact_exists(conn, email=None, phone=None):
    filters = []
    params = []
    normalized_email = _normalize_email(email) if email else None
    normalized_phone = _normalize_phone(phone) if phone else None
    if normalized_email:
        filters.append("LOWER(email) = ?")
        params.append(normalized_email)
    if normalized_phone:
        filters.append("phone = ?")
        params.append(normalized_phone)
    if not filters:
        return False
    row = _row_to_dict(
        conn.execute(
            """
            SELECT id
            FROM simulation_targets
            WHERE archived_at IS NULL
              AND source = 'directory'
              AND ({})
            LIMIT 1
            """.format(" OR ".join(filters)),
            params,
        )
    )
    return row is not None


def preview_directory_sync(conn, provider_id, group_ids=None, requested_by=None):
    provider = _directory_provider_or_error(conn, provider_id)
    result = preview_directory_users(conn, provider_id, group_ids=group_ids)
    job_id = _create_directory_sync_job(conn, provider_id, "preview", result.selected_group_ids, requested_by)
    _record_directory_sync_audit_event(
        conn,
        provider_id,
        job_id,
        "preview_started",
        "Directory sync preview started.",
        actor=requested_by,
        metadata={"selected_groups": list(result.selected_group_ids)},
    )
    stage_counts = _stage_directory_sync_users(conn, provider, job_id, result)
    status = "completed_with_errors" if stage_counts["invalid_count"] else "completed"
    _update_directory_sync_job(
        conn,
        job_id,
        status,
        total_groups=len(result.groups),
        total_users=len(result.users),
        staged_count=stage_counts["staged_count"],
        invalid_count=stage_counts["invalid_count"],
        validation_errors=stage_counts["validation_errors"],
    )
    _update_directory_provider_sync_state(conn, provider_id, job_id, status)
    _record_directory_sync_audit_event(
        conn,
        provider_id,
        job_id,
        "preview_completed",
        "Directory sync preview staged {} users.".format(stage_counts["staged_count"]),
        actor=requested_by,
        metadata={"invalid_count": stage_counts["invalid_count"]},
    )
    return get_directory_sync_job_results(conn, job_id)


def sync_directory_users(conn, provider_id, group_ids=None, campaign_id=None, requested_by=None):
    provider = _directory_provider_or_error(conn, provider_id)
    destination_campaign_id = campaign_id or _directory_default_campaign_id(conn)
    if not get_campaign(conn, destination_campaign_id):
        raise ValueError("Unknown simulation campaign id: {}".format(destination_campaign_id))
    result = sync_directory_staged_users(conn, provider_id, group_ids=group_ids)
    job_id = _create_directory_sync_job(conn, provider_id, "sync", result.selected_group_ids, requested_by)
    _record_directory_sync_audit_event(
        conn,
        provider_id,
        job_id,
        "sync_started",
        "Directory sync import started.",
        actor=requested_by,
        metadata={"campaign_id": destination_campaign_id, "selected_groups": list(result.selected_group_ids)},
    )
    stage_counts = _stage_directory_sync_users(conn, provider, job_id, result)
    imported_count = 0
    skipped_count = 0
    duplicate_count = 0
    staged_users = _rows_to_dicts(
        conn.execute(
            """
            SELECT id, active, validation_status, target_payload_json
            FROM staged_directory_users
            WHERE sync_job_id = ?
            ORDER BY id ASC
            """,
            (job_id,),
        )
    )
    for staged in staged_users:
        payload = _json_dict(staged["target_payload_json"])
        if not _bool(staged["active"]) or staged["validation_status"] != "valid":
            skipped_count += 1
            continue
        if _target_contact_exists(conn, email=payload.get("email"), phone=payload.get("phone")):
            duplicate_count += 1
            skipped_count += 1
            continue
        target = create_target(conn, destination_campaign_id, **payload)
        conn.execute(
            """
            UPDATE staged_directory_users
            SET imported_target_id = ?, imported_at = ?
            WHERE id = ?
            """,
            (target["id"], _utc_now(), staged["id"]),
        )
        conn.commit()
        imported_count += 1
    status = "completed_with_errors" if stage_counts["invalid_count"] else "completed"
    _update_directory_sync_job(
        conn,
        job_id,
        status,
        total_groups=len(result.groups),
        total_users=len(result.users),
        staged_count=stage_counts["staged_count"],
        imported_count=imported_count,
        skipped_count=skipped_count,
        invalid_count=stage_counts["invalid_count"],
        duplicate_count=duplicate_count,
        validation_errors=stage_counts["validation_errors"],
    )
    _update_directory_provider_sync_state(conn, provider_id, job_id, status)
    _record_directory_sync_audit_event(
        conn,
        provider_id,
        job_id,
        "sync_completed",
        "Directory sync imported {} users and skipped {} users.".format(imported_count, skipped_count),
        actor=requested_by,
        metadata={
            "campaign_id": destination_campaign_id,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
        },
    )
    return get_directory_sync_job_results(conn, job_id)


def get_directory_sync_job_results(conn, job_id):
    job = _directory_sync_job_response(
        _row_to_dict(
            conn.execute(
                """
                SELECT
                    id, provider_id, job_type, status, selected_groups_json,
                    total_groups, total_users, staged_count, imported_count,
                    skipped_count, invalid_count, duplicate_count,
                    validation_errors_json, requested_by, started_at,
                    completed_at, created_at, updated_at
                FROM directory_sync_jobs
                WHERE id = ?
                """,
                (job_id,),
            )
        )
    )
    if not job:
        return None
    provider = get_directory_provider_settings(conn, job["provider_id"])
    staged_users = [
        _staged_directory_user_response(row)
        for row in _rows_to_dicts(
            conn.execute(
                """
                SELECT
                    id, provider_id, sync_job_id, external_user_id,
                    user_principal_name, mail, display_name, given_name,
                    surname, job_title, department, office_location,
                    mobile_phone, business_phones_json, manager, groups_json,
                    source_group_ids_json, active, validation_status,
                    validation_errors_json, target_payload_json,
                    imported_target_id, staged_at, imported_at
                FROM staged_directory_users
                WHERE sync_job_id = ?
                ORDER BY display_name ASC, id ASC
                """,
                (job_id,),
            )
        )
    ]
    audit_events = [
        _directory_sync_audit_event_response(row)
        for row in _rows_to_dicts(
            conn.execute(
                """
                SELECT
                    id, provider_id, sync_job_id, event_type, severity,
                    actor, message, metadata_json, created_at
                FROM directory_sync_audit_events
                WHERE sync_job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            )
        )
    ]
    return {
        "job": job,
        "provider": provider,
        "staged_users": staged_users,
        "audit_events": audit_events,
    }


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


def list_ai_generation_audits(conn, provider_id=None, status=None):
    """Return AI generation audit records without provider credential material."""
    params = []
    filters = []
    if provider_id is not None:
        filters.append("provider_id = ?")
        params.append(provider_id)
    if status is not None:
        filters.append("status = ?")
        params.append(status)
    where = "WHERE {}".format(" AND ".join(filters)) if filters else ""
    cursor = conn.execute(
        f"""
        SELECT
            id,
            provider_id,
            provider_name,
            provider_type,
            model_name,
            request_json,
            output_json,
            risk_flags,
            safety_notes,
            metadata,
            status,
            error_reason,
            created_at
        FROM ai_generation_audits
        {where}
        ORDER BY created_at DESC, id DESC
        """,
        params,
    )
    return [_audit_response(row) for row in _rows_to_dicts(cursor)]


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


def generate_ai_scenario(conn, provider_id, request):
    """Generate guarded drafts and audit the request, provider, output, and risks."""
    from core.ai_generation import generate_scenario_with_provider_settings

    provider = _row_to_dict(
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
    if not provider:
        raise ValueError("Unknown AI provider config id: {}".format(provider_id))
    provider_settings = _provider_response(provider)
    try:
        response = generate_scenario_with_provider_settings(provider_settings, request)
    except Exception as exc:
        _record_ai_generation_audit(
            conn,
            provider_settings,
            request,
            status="blocked",
            error_reason=str(exc),
            risk_flags=getattr(exc, "risk_flags", []),
        )
        raise

    _record_ai_generation_audit(conn, provider_settings, request, response=response)
    return response


def list_ai_campaign_drafts(conn, campaign_id=None):
    """Return saved AI-generated campaign drafts with preserved history."""
    params = []
    where = ""
    if campaign_id is not None:
        where = "WHERE d.campaign_id = ?"
        params.append(campaign_id)
    rows = _rows_to_dicts(
        conn.execute(
            f"""
            SELECT
                d.id,
                d.campaign_id,
                c.name AS campaign_name,
                d.audit_id,
                d.provider_id,
                d.provider_name,
                d.provider_type,
                d.model_name,
                d.channels,
                d.email_subject,
                d.email_body,
                d.sms_body,
                d.voice_script,
                d.landing_text,
                d.training_text,
                d.risk_flags,
                d.safety_notes,
                d.metadata,
                d.status,
                d.created_at,
                d.updated_at
            FROM ai_campaign_drafts d
            JOIN simulation_campaigns c ON c.id = d.campaign_id
            {where}
            ORDER BY d.created_at DESC, d.id DESC
            """,
            params,
        )
    )
    return [_ai_draft_response(row) for row in rows]


def save_ai_campaign_draft(
    conn,
    campaign_id,
    draft,
    channels,
    provider=None,
    risk_flags=None,
    safety_notes=None,
    metadata=None,
    audit_id=None,
    status="approved",
):
    """Persist approved AI drafts as campaign simulation content."""
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))

    draft = draft or {}
    provider = provider or {}
    normalized_channels = _normalize_channels(channels)
    now = _utc_now()
    cursor = conn.execute(
        """
        INSERT INTO ai_campaign_drafts (
            campaign_id, audit_id, provider_id, provider_name, provider_type,
            model_name, channels, email_subject, email_body, sms_body,
            voice_script, landing_text, training_text, risk_flags,
            safety_notes, metadata, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            audit_id,
            provider.get("id") or provider.get("provider_id"),
            _normalize_text(provider.get("name") or provider.get("provider_name")),
            _normalize_text(provider.get("provider_type")),
            _normalize_text(provider.get("model_name")),
            json.dumps(normalized_channels),
            _normalize_text(draft.get("email_subject")),
            _normalize_text(draft.get("email_body")),
            _normalize_text(draft.get("sms_body")),
            _normalize_text(draft.get("voice_script")),
            _normalize_text(draft.get("landing_text")),
            _normalize_text(draft.get("training_text")),
            json.dumps(list(risk_flags or []), sort_keys=True),
            json.dumps(list(safety_notes or []), sort_keys=True),
            _safe_json_dumps(metadata),
            _normalize_text(status) or "approved",
            now,
            now,
        ),
    )
    conn.commit()
    return list_ai_campaign_drafts(conn, campaign_id)[0] if cursor.lastrowid else None
