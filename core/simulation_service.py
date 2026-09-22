import csv
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from io import StringIO
import json
import re


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


def _safe_json_dumps(value):
    return json.dumps(value or {}, sort_keys=True)


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


def get_campaign_detail(conn, campaign_id, include_archived_targets=True):
    campaign = get_campaign(conn, campaign_id)
    if not campaign:
        raise ValueError("Unknown simulation campaign id: {}".format(campaign_id))
    return {
        "campaign": campaign,
        "targets": list_targets(conn, campaign_id, include_archived=include_archived_targets),
        "metrics": get_campaign_metrics(conn, campaign_id),
        "import_batches": list_import_batches(conn, campaign_id),
        "events": list_simulation_events(conn, campaign_id),
    }


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
