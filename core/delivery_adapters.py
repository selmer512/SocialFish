from dataclasses import dataclass, field
import json
from typing import Any, Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable


DELIVERY_SIMULATION_LABEL = "authorized_security_awareness_delivery"
VALID_DELIVERY_CHANNELS = {"email", "sms", "voice"}


def _clean_text(value):
    normalized = str(value or "").strip()
    return normalized or None


def _json_dict(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_channel(channel):
    normalized = (_clean_text(channel) or "").lower()
    if normalized not in VALID_DELIVERY_CHANNELS:
        raise ValueError("Delivery channel must be one of: {}".format(", ".join(sorted(VALID_DELIVERY_CHANNELS))))
    return normalized


@dataclass(frozen=True)
class DeliveryProviderConfig:
    """UI-managed delivery provider settings without credential material."""

    id: int
    channel: str
    provider_key: str
    provider_name: str
    provider_type: str = "dry_run"
    enabled: bool = False
    settings: Dict[str, Any] = field(default_factory=dict)
    required_settings: Tuple[str, ...] = field(default_factory=tuple)
    secret_configured: bool = False
    last_error_message: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "channel", _normalize_channel(self.channel))
        object.__setattr__(self, "provider_key", _clean_text(self.provider_key) or self.provider_type)
        object.__setattr__(self, "provider_name", _clean_text(self.provider_name) or self.provider_key)
        object.__setattr__(self, "provider_type", (_clean_text(self.provider_type) or "dry_run").lower())
        object.__setattr__(self, "settings", dict(self.settings or {}))
        object.__setattr__(
            self,
            "required_settings",
            tuple(_clean_text(value) for value in self.required_settings if _clean_text(value)),
        )

    @classmethod
    def from_settings(cls, settings):
        return cls(
            id=int(settings["id"]),
            channel=settings["channel"],
            provider_key=settings["provider_key"],
            provider_name=settings["provider_name"],
            provider_type=settings.get("provider_type") or "dry_run",
            enabled=bool(settings.get("enabled")),
            settings=_json_dict(settings.get("settings") or settings.get("settings_json")),
            required_settings=tuple(_json_list(settings.get("required_settings") or settings.get("required_settings_json"))),
            secret_configured=bool(settings.get("secret_configured"))
            or settings.get("secret_placeholder") == "configured",
            last_error_message=settings.get("last_error_message"),
        )


@dataclass(frozen=True)
class DeliveryMessage:
    channel: str
    subject: Optional[str] = None
    body: Optional[str] = None
    content: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "channel", _normalize_channel(self.channel))
        object.__setattr__(self, "subject", _clean_text(self.subject))
        object.__setattr__(self, "body", _clean_text(self.body))
        content = dict(self.content or {})
        content.setdefault("artifact_label", DELIVERY_SIMULATION_LABEL)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class DeliveryRecipient:
    target_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "name", _clean_text(self.name) or "Training participant")
        object.__setattr__(self, "email", _clean_text(self.email))
        object.__setattr__(self, "phone", _clean_text(self.phone))


@dataclass(frozen=True)
class DeliveryAttemptRequest:
    campaign_id: int
    target_id: int
    channel: str
    message: DeliveryMessage
    recipient: DeliveryRecipient
    delivery_job_id: Optional[int] = None
    attempt_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        channel = _normalize_channel(self.channel)
        if self.message.channel != channel:
            raise ValueError("Message channel must match delivery attempt channel.")
        if self.recipient.target_id != self.target_id:
            raise ValueError("Recipient target id must match delivery attempt target id.")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


@dataclass(frozen=True)
class DeliveryProviderResult:
    status: str
    event_type: str
    provider: str
    provider_message_id: Optional[str] = None
    provider_response: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    event_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "status", (_clean_text(self.status) or "failed").lower())
        object.__setattr__(self, "event_type", (_clean_text(self.event_type) or self.status).lower())
        object.__setattr__(self, "provider", _clean_text(self.provider) or "unknown")
        object.__setattr__(self, "provider_message_id", _clean_text(self.provider_message_id))
        object.__setattr__(self, "provider_response", dict(self.provider_response or {}))
        object.__setattr__(self, "error_message", _clean_text(self.error_message))
        object.__setattr__(self, "event_metadata", dict(self.event_metadata or {}))


@runtime_checkable
class DeliveryProviderAdapter(Protocol):
    provider_type: str

    def send(self, request: DeliveryAttemptRequest, provider_config: DeliveryProviderConfig) -> DeliveryProviderResult:
        """Execute or simulate a delivery attempt through a provider."""


class DeliveryProviderError(Exception):
    """Base error for delivery provider failures."""


class DeliveryDisabledProviderError(DeliveryProviderError):
    """Raised when a disabled delivery provider is selected."""


class DeliveryProviderConfigurationError(DeliveryProviderError):
    """Raised when provider settings are incomplete or unavailable."""


class DeliveryProviderTypeError(DeliveryProviderError):
    """Raised when no adapter exists for a configured provider type."""


def _require_channel(provider_config, channel):
    if provider_config.channel != _normalize_channel(channel):
        raise DeliveryProviderConfigurationError(
            "Provider '{}' is configured for {} delivery, not {}.".format(
                provider_config.provider_name,
                provider_config.channel,
                channel,
            )
        )


def _require_enabled(provider_config):
    if not provider_config.enabled:
        raise DeliveryDisabledProviderError("Delivery provider '{}' is disabled.".format(provider_config.provider_name))


def _require_settings(provider_config):
    missing = [
        key
        for key in provider_config.required_settings
        if _clean_text(provider_config.settings.get(key)) is None
    ]
    if missing:
        raise DeliveryProviderConfigurationError(
            "Delivery provider '{}' is missing required settings: {}.".format(
                provider_config.provider_name,
                ", ".join(missing),
            )
        )


class BaseDryRunDeliveryAdapter:
    """Offline adapter that returns deterministic simulated provider results."""

    provider_type = "dry_run"
    channel = None

    def _result_metadata(self, request, provider_config):
        return {
            "artifact_label": DELIVERY_SIMULATION_LABEL,
            "dry_run": True,
            "external_delivery": False,
            "provider_id": provider_config.id,
            "provider_key": provider_config.provider_key,
            "delivery_job_id": request.delivery_job_id,
            "attempt_id": request.attempt_id,
        }

    def send(self, request, provider_config):
        _require_channel(provider_config, self.channel)
        _require_enabled(provider_config)
        provider_message_id = "dry-run-{}-{}-{}".format(
            request.channel,
            request.campaign_id,
            request.target_id,
        )
        return DeliveryProviderResult(
            status="delivered",
            event_type="delivered",
            provider=provider_config.provider_key,
            provider_message_id=provider_message_id,
            provider_response={
                "dry_run": True,
                "channel": request.channel,
                "external_delivery": False,
                "message_recorded": True,
            },
            event_metadata=self._result_metadata(request, provider_config),
        )


class DryRunEmailDeliveryAdapter(BaseDryRunDeliveryAdapter):
    channel = "email"


class DryRunSMSDeliveryAdapter(BaseDryRunDeliveryAdapter):
    channel = "sms"


class DryRunVoiceDeliveryAdapter(BaseDryRunDeliveryAdapter):
    channel = "voice"

    def send(self, request, provider_config):
        result = super().send(request, provider_config)
        response = dict(result.provider_response)
        response["simulated_voice_response"] = "completed_training"
        metadata = dict(result.event_metadata)
        metadata["voice_response"] = "completed_training"
        return DeliveryProviderResult(
            status=result.status,
            event_type=result.event_type,
            provider=result.provider,
            provider_message_id=result.provider_message_id,
            provider_response=response,
            event_metadata=metadata,
        )


class SMTPEmailDeliveryAdapter:
    """Configuration-ready SMTP shell; execution waits for credential retrieval."""

    provider_type = "smtp"

    def build_payload(self, request, provider_config):
        _require_channel(provider_config, "email")
        _require_enabled(provider_config)
        _require_settings(provider_config)
        return {
            "smtp_host": provider_config.settings.get("smtp_host"),
            "smtp_port": provider_config.settings.get("smtp_port"),
            "from_email": provider_config.settings.get("from_email"),
            "recipient": request.recipient.email,
            "subject": request.message.subject,
            "body": request.message.body,
            "metadata": {"artifact_label": DELIVERY_SIMULATION_LABEL},
        }

    def send(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise DeliveryProviderConfigurationError(
            "SMTP delivery is not enabled until UI-managed credential retrieval is implemented."
        )


class EmailAPIDeliveryAdapter:
    """Configuration-ready shell for email API providers."""

    provider_type = "email_api"

    def build_payload(self, request, provider_config):
        _require_channel(provider_config, "email")
        _require_enabled(provider_config)
        _require_settings(provider_config)
        if not provider_config.secret_configured:
            raise DeliveryProviderConfigurationError(
                "Delivery provider '{}' requires credentials configured through the UI.".format(
                    provider_config.provider_name
                )
            )
        return {
            "from_email": provider_config.settings.get("from_email"),
            "recipient": request.recipient.email,
            "subject": request.message.subject,
            "body": request.message.body,
            "metadata": {"artifact_label": DELIVERY_SIMULATION_LABEL},
        }

    def send(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise DeliveryProviderConfigurationError(
            "Email API delivery is not enabled until provider-specific send logic is implemented."
        )


class SMSAPIDeliveryAdapter:
    provider_type = "sms_api"

    def build_payload(self, request, provider_config):
        _require_channel(provider_config, "sms")
        _require_enabled(provider_config)
        _require_settings(provider_config)
        if not provider_config.secret_configured:
            raise DeliveryProviderConfigurationError(
                "Delivery provider '{}' requires credentials configured through the UI.".format(
                    provider_config.provider_name
                )
            )
        return {
            "sender_id": provider_config.settings.get("sender_id"),
            "recipient": request.recipient.phone,
            "body": request.message.body,
            "metadata": {"artifact_label": DELIVERY_SIMULATION_LABEL},
        }

    def send(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise DeliveryProviderConfigurationError(
            "SMS API delivery is not enabled until provider-specific send logic is implemented."
        )


class VoiceAPIDeliveryAdapter:
    provider_type = "voice_api"

    def build_payload(self, request, provider_config):
        _require_channel(provider_config, "voice")
        _require_enabled(provider_config)
        _require_settings(provider_config)
        if not provider_config.secret_configured:
            raise DeliveryProviderConfigurationError(
                "Delivery provider '{}' requires credentials configured through the UI.".format(
                    provider_config.provider_name
                )
            )
        return {
            "caller_id": provider_config.settings.get("caller_id"),
            "recipient": request.recipient.phone,
            "script": request.message.body,
            "metadata": {"artifact_label": DELIVERY_SIMULATION_LABEL},
        }

    def send(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise DeliveryProviderConfigurationError(
            "Voice API delivery is not enabled until provider-specific call logic is implemented."
        )


def provider_for_config(provider_config):
    provider_type = (provider_config.provider_type or "").strip().lower()
    provider_key = (provider_config.provider_key or "").strip().lower()
    if provider_type == "dry_run":
        if provider_config.channel == "email" or provider_key == "dry_run_email":
            return DryRunEmailDeliveryAdapter()
        if provider_config.channel == "sms" or provider_key == "dry_run_sms":
            return DryRunSMSDeliveryAdapter()
        if provider_config.channel == "voice" or provider_key == "dry_run_voice":
            return DryRunVoiceDeliveryAdapter()
    if provider_type == "smtp":
        return SMTPEmailDeliveryAdapter()
    if provider_type == "email_api":
        return EmailAPIDeliveryAdapter()
    if provider_type == "sms_api":
        return SMSAPIDeliveryAdapter()
    if provider_type == "voice_api":
        return VoiceAPIDeliveryAdapter()
    raise DeliveryProviderTypeError("Unsupported delivery provider type: {}".format(provider_config.provider_type))


def send_with_provider_settings(settings, request):
    provider_config = DeliveryProviderConfig.from_settings(settings)
    provider = provider_for_config(provider_config)
    return provider.send(request, provider_config)
