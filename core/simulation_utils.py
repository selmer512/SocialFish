from datetime import UTC, datetime
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


def utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_text(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def json_loads(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def json_dict(value):
    parsed = json_loads(value, {})
    return dict(parsed) if isinstance(parsed, dict) else {}


def json_list(value):
    if isinstance(value, tuple):
        return list(value)
    parsed = json_loads(value, [])
    return list(parsed) if isinstance(parsed, list) else []


def safe_json_dumps(value):
    return json.dumps(value or {}, sort_keys=True)


def rows_to_dicts(cursor):
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def row_to_dict(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row))


def db_bool(value):
    return bool(int(value or 0))


def normalize_choice(value, valid_choices, field_name, default=None):
    normalized = (clean_text(value) or default or "").lower()
    if normalized not in valid_choices:
        raise ValueError("{} must be one of: {}".format(field_name, ", ".join(sorted(valid_choices))))
    return normalized


def select_enabled_provider(providers, preferred_type=None):
    normalized_type = clean_text(preferred_type)
    if normalized_type:
        normalized_type = normalized_type.lower()
        for provider in providers:
            if provider.get("provider_type") == normalized_type and provider.get("enabled"):
                return provider
    for provider in providers:
        if provider.get("enabled"):
            return provider
    return None


def is_sensitive_key(key):
    normalized = str(key or "").lower()
    if normalized.endswith(SAFE_SECRET_KEY_SUFFIXES):
        return False
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_sensitive_value(value, redacted_value=REDACTED_VALUE):
    if isinstance(value, dict):
        redacted = {}
        for key, nested in value.items():
            if is_sensitive_key(key):
                redacted[key] = redacted_value
            else:
                redacted[key] = redact_sensitive_value(nested, redacted_value)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_value(item, redacted_value) for item in value]
    return value
