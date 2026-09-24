from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from core.simulation_utils import clean_text as _clean_text


AI_GENERATION_LABEL = "authorized_security_awareness_training"
VALID_AI_CHANNELS = {"email", "sms", "voice"}
VALID_AI_DIFFICULTIES = {"introductory", "standard", "advanced"}
BLOCKED_REQUEST_PATTERNS = (
    (re.compile(r"\b(capture|collect|harvest|steal|exfiltrate)\b.{0,40}\b(passwords?|credentials?|logins?|tokens?|mfa|otp)\b", re.I), "credential_harvesting_request"),
    (re.compile(r"\b(passwords?|credentials?|logins?|tokens?|mfa|otp)\b.{0,40}\b(capture|collect|harvest|steal|exfiltrate)\b", re.I), "credential_harvesting_request"),
    (re.compile(r"\b(bypass|disable|evade)\b.{0,40}\b(mfa|2fa|security|detection|filter)\b", re.I), "offensive_capability_request"),
    (re.compile(r"\b(impersonate|spoof|clone)\b.{0,40}\b(microsoft|google|okta|duo|apple|amazon|paypal|bank|irs|docusign)\b", re.I), "real_brand_impersonation_request"),
)
BLOCKED_OUTPUT_PATTERNS = (
    (re.compile(r"(?<!do not )(?<!never )\b(enter|submit|provide|share|send)\b.{0,40}\b(passwords?|credentials?|logins?|tokens?|mfa|otp)\b", re.I), "credential_harvesting_output"),
    (re.compile(r"\b(ignore|bypass|disable)\b.{0,40}\b(security|mfa|2fa|warning|filter)\b", re.I), "offensive_capability_output"),
)


def _normalize_channels(channels):
    values = []
    if isinstance(channels, str):
        values = [channels]
    elif channels:
        values = list(channels)

    normalized = []
    for channel in values:
        channel_value = (_clean_text(channel) or "").lower()
        if not channel_value:
            continue
        if channel_value not in VALID_AI_CHANNELS:
            raise ValueError("AI generation channel must be one of: {}".format(", ".join(sorted(VALID_AI_CHANNELS))))
        if channel_value not in normalized:
            normalized.append(channel_value)

    if not normalized:
        raise ValueError("At least one AI generation channel is required.")
    return tuple(normalized)


@dataclass(frozen=True)
class AIProviderConfig:
    """Provider metadata loaded from the UI-managed ai_provider_configs table.

    Adapter implementations receive this shape instead of reading environment
    variables or hard-coded secrets. Secret material is intentionally absent;
    Phase 01 only exposes whether a secret has been configured.
    """

    id: int
    name: str
    provider_type: str
    model_name: str
    base_url: Optional[str] = None
    enabled: bool = False
    secret_configured: bool = False
    description: Optional[str] = None

    @classmethod
    def from_settings(cls, settings):
        return cls(
            id=int(settings["id"]),
            name=settings["name"],
            provider_type=settings["provider_type"],
            model_name=settings["model_name"],
            base_url=settings.get("base_url"),
            enabled=bool(settings.get("enabled")),
            secret_configured=bool(settings.get("secret_configured")),
            description=settings.get("description"),
        )


@dataclass(frozen=True)
class AIScenarioRequest:
    """Provider-neutral request for authorized simulation draft generation.

    The contract captures the scenario goal, audience, desired delivery
    channels, tone, difficulty, safety constraints, and optional campaign
    context. Providers must treat this as an authorized training-only prompt
    source and must not infer offensive capability requests from campaign data.
    """

    scenario_goal: str
    audience: str
    channels: Sequence[str]
    tone: str = "professional"
    difficulty: str = "standard"
    safety_constraints: Sequence[str] = field(default_factory=tuple)
    campaign_context: Dict[str, Any] = field(default_factory=dict)
    training_reminder: Optional[str] = None

    def __post_init__(self):
        goal = _clean_text(self.scenario_goal)
        audience = _clean_text(self.audience)
        tone = _clean_text(self.tone) or "professional"
        difficulty = (_clean_text(self.difficulty) or "standard").lower()

        if not goal:
            raise ValueError("AI scenario goal is required.")
        if not audience:
            raise ValueError("AI scenario audience is required.")
        if difficulty not in VALID_AI_DIFFICULTIES:
            raise ValueError(
                "AI generation difficulty must be one of: {}".format(", ".join(sorted(VALID_AI_DIFFICULTIES)))
            )

        constraints = tuple(
            constraint
            for constraint in (_clean_text(value) for value in self.safety_constraints)
            if constraint
        )
        object.__setattr__(self, "scenario_goal", goal)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "channels", _normalize_channels(self.channels))
        object.__setattr__(self, "tone", tone)
        object.__setattr__(self, "difficulty", difficulty)
        object.__setattr__(self, "safety_constraints", constraints)
        object.__setattr__(self, "campaign_context", dict(self.campaign_context or {}))
        object.__setattr__(self, "training_reminder", _clean_text(self.training_reminder))

    def requested_channels(self):
        return set(self.channels)


@dataclass(frozen=True)
class AIGeneratedDraft:
    """Provider-neutral generated content for email, SMS, voice, and training.

    Providers may populate only the channel fields requested by
    AIScenarioRequest.channels, but response metadata must always label the
    artifact as authorized security awareness training.
    """

    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    sms_body: Optional[str] = None
    voice_script: Optional[str] = None
    landing_text: Optional[str] = None
    training_text: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        metadata = dict(self.metadata or {})
        metadata.setdefault("artifact_label", AI_GENERATION_LABEL)
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class AIGenerationResponse:
    """Provider-neutral response returned by every AI generation adapter.

    The response carries generated draft text, provider/model identifiers,
    channel coverage, risk flags for reviewers, safety notes, and metadata for
    later audit logging. It intentionally contains no provider credentials.
    """

    provider_id: int
    provider_name: str
    provider_type: str
    model_name: str
    channels: Tuple[str, ...]
    draft: AIGeneratedDraft
    risk_flags: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        metadata = dict(self.metadata or {})
        metadata.setdefault("artifact_label", AI_GENERATION_LABEL)
        object.__setattr__(self, "channels", _normalize_channels(self.channels))
        object.__setattr__(self, "risk_flags", list(self.risk_flags or []))
        object.__setattr__(self, "safety_notes", list(self.safety_notes or []))
        object.__setattr__(self, "metadata", metadata)


@runtime_checkable
class AIScenarioProvider(Protocol):
    """Common interface for local mock, cloud HTTP, and local HTTP providers."""

    provider_type: str

    def generate(self, request: AIScenarioRequest, provider_config: AIProviderConfig) -> AIGenerationResponse:
        """Generate authorized awareness-training drafts from the shared contract."""


class AIGenerationError(Exception):
    """Base error for AI scenario generation failures."""


class AIDisabledProviderError(AIGenerationError):
    """Raised when a disabled provider is selected for generation."""


class AIProviderConfigurationError(AIGenerationError):
    """Raised when provider settings are incomplete or unavailable."""


class AIProviderTypeError(AIGenerationError):
    """Raised when no adapter exists for a configured provider type."""


class AIContentPolicyError(AIGenerationError):
    """Raised when a request or generated artifact violates training guardrails."""

    def __init__(self, message, risk_flags=None):
        super().__init__(message)
        self.risk_flags = list(risk_flags or [])


def _require_enabled(provider_config):
    if not provider_config.enabled:
        raise AIDisabledProviderError("AI provider '{}' is disabled.".format(provider_config.name))


def _join_constraints(request):
    if not request.safety_constraints:
        return "Use only authorized security awareness training language."
    return " ".join(request.safety_constraints)


def _joined_request_text(request):
    pieces = [
        request.scenario_goal,
        request.audience,
        request.tone,
        request.difficulty,
        request.training_reminder,
        " ".join(request.safety_constraints),
    ]
    pieces.extend(str(value) for value in request.campaign_context.values())
    return "\n".join(str(piece or "") for piece in pieces)


def _draft_text(draft):
    return "\n".join(
        str(value or "")
        for value in (
            draft.email_subject,
            draft.email_body,
            draft.sms_body,
            draft.voice_script,
            draft.landing_text,
            draft.training_text,
        )
    )


def _pattern_flags(text, patterns):
    return [flag for pattern, flag in patterns if pattern.search(text or "")]


def validate_generation_request(request):
    """Block requests that ask for harmful capability outside training simulations."""
    risk_flags = _pattern_flags(_joined_request_text(request), BLOCKED_REQUEST_PATTERNS)
    if risk_flags:
        raise AIContentPolicyError(
            "AI generation request was blocked by safety guardrails: {}".format(", ".join(sorted(set(risk_flags)))),
            risk_flags=sorted(set(risk_flags)),
        )


def validate_generation_response(response):
    """Require authorized-training labeling and reject unsafe generated artifacts."""
    labels = {
        response.metadata.get("artifact_label"),
        response.draft.metadata.get("artifact_label"),
    }
    risk_flags = []
    if AI_GENERATION_LABEL not in labels or len(labels) != 1:
        risk_flags.append("missing_authorized_training_label")
    risk_flags.extend(_pattern_flags(_draft_text(response.draft), BLOCKED_OUTPUT_PATTERNS))
    if risk_flags:
        raise AIContentPolicyError(
            "AI generated artifact was blocked by safety guardrails: {}".format(", ".join(sorted(set(risk_flags)))),
            risk_flags=sorted(set(risk_flags)),
        )
    return response


class LocalMockScenarioProvider:
    """Deterministic offline provider for safe awareness-training drafts."""

    provider_type = "local"

    def generate(self, request, provider_config):
        validate_generation_request(request)
        _require_enabled(provider_config)

        topic = request.scenario_goal
        audience = request.audience
        tone = request.tone
        reminder = request.training_reminder or "Pause, verify the request through an approved channel, and report concerns."
        context_name = request.campaign_context.get("campaign_name") or request.campaign_context.get("name")
        context_suffix = " for {}".format(context_name) if context_name else ""

        draft_kwargs = {
            "landing_text": (
                "Authorized security awareness training{}: review the scenario, identify warning signs, "
                "and practice reporting suspicious messages."
            ).format(context_suffix),
            "training_text": "{} This exercise is authorized training for {}.".format(reminder, audience),
            "metadata": {
                "artifact_label": AI_GENERATION_LABEL,
                "deterministic": True,
                "provider_shape": "local_mock",
            },
        }

        if "email" in request.requested_channels():
            draft_kwargs["email_subject"] = "Training simulation: {}".format(topic)
            draft_kwargs["email_body"] = (
                "Hello {},\n\n"
                "This authorized security awareness training simulation focuses on {}. "
                "The tone is {} and the difficulty is {}. No credentials or sensitive information "
                "should be entered during this exercise.\n\n{}"
            ).format(audience, topic, tone, request.difficulty, reminder)

        if "sms" in request.requested_channels():
            draft_kwargs["sms_body"] = (
                "Authorized training simulation for {}: {}. Do not share credentials. {}"
            ).format(audience, topic, reminder)

        if "voice" in request.requested_channels():
            draft_kwargs["voice_script"] = (
                "Hello. This is an authorized security awareness training simulation for {}. "
                "The scenario is {}. Ask the participant to verify the request, avoid sharing "
                "credentials, and use the approved reporting process."
            ).format(audience, topic)

        return validate_generation_response(AIGenerationResponse(
            provider_id=provider_config.id,
            provider_name=provider_config.name,
            provider_type=provider_config.provider_type,
            model_name=provider_config.model_name,
            channels=tuple(request.channels),
            draft=AIGeneratedDraft(**draft_kwargs),
            risk_flags=[
                "authorized_training_label_present",
                "credential_collection_disallowed",
                "real_brand_impersonation_omitted",
            ],
            safety_notes=[
                "Generated locally without network access.",
                "Draft text explicitly states this is authorized security awareness training.",
                "No provider credentials were read or returned.",
            ],
            metadata={
                "artifact_label": AI_GENERATION_LABEL,
                "provider_shape": "local_mock",
                "safety_constraints": _join_constraints(request),
            },
        ))


class OpenAICompatibleHTTPProvider:
    """Configuration-ready shell for OpenAI-compatible chat/completions APIs."""

    provider_type = "cloud"

    def build_payload(self, request, provider_config):
        validate_generation_request(request)
        _require_enabled(provider_config)
        if not provider_config.base_url:
            raise AIProviderConfigurationError("AI provider '{}' requires a base URL.".format(provider_config.name))
        if not provider_config.secret_configured:
            raise AIProviderConfigurationError(
                "AI provider '{}' requires credentials configured through the UI.".format(provider_config.name)
            )
        return {
            "model": provider_config.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Create only authorized security awareness training simulation drafts. "
                        "Do not request credentials, impersonate real brands by default, or provide offensive instructions."
                    ),
                },
                {
                    "role": "user",
                    "content": {
                        "scenario_goal": request.scenario_goal,
                        "audience": request.audience,
                        "channels": list(request.channels),
                        "tone": request.tone,
                        "difficulty": request.difficulty,
                        "safety_constraints": list(request.safety_constraints),
                        "campaign_context": request.campaign_context,
                        "training_reminder": request.training_reminder,
                    },
                },
            ],
            "response_format": {"type": "json_object"},
        }

    def generate(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise AIProviderConfigurationError(
            "OpenAI-compatible HTTP generation is not enabled until UI-managed credential retrieval is implemented."
        )


class LocalHTTPModelServerProvider(OpenAICompatibleHTTPProvider):
    """Configuration-ready shell for local HTTP model servers."""

    provider_type = "local_http"

    def build_payload(self, request, provider_config):
        validate_generation_request(request)
        _require_enabled(provider_config)
        if not provider_config.base_url:
            raise AIProviderConfigurationError(
                "Local HTTP AI provider '{}' requires a base URL.".format(provider_config.name)
            )
        return {
            "model": provider_config.model_name,
            "prompt": {
                "scenario_goal": request.scenario_goal,
                "audience": request.audience,
                "channels": list(request.channels),
                "tone": request.tone,
                "difficulty": request.difficulty,
                "safety_constraints": list(request.safety_constraints),
                "campaign_context": request.campaign_context,
                "training_reminder": request.training_reminder,
                "artifact_label": AI_GENERATION_LABEL,
            },
            "stream": False,
        }

    def generate(self, request, provider_config):
        self.build_payload(request, provider_config)
        raise AIProviderConfigurationError(
            "Local HTTP model generation is not enabled until response parsing is implemented for this server shape."
        )


def provider_for_config(provider_config):
    provider_type = (provider_config.provider_type or "").strip().lower()
    if provider_type in {"local", "mock", "local_mock"}:
        return LocalMockScenarioProvider()
    if provider_type in {"cloud", "openai", "openai_compatible", "openai-compatible"}:
        return OpenAICompatibleHTTPProvider()
    if provider_type in {"local_http", "local-http", "local_model", "local-model"}:
        return LocalHTTPModelServerProvider()
    raise AIProviderTypeError("Unsupported AI provider type: {}".format(provider_config.provider_type))


def generate_scenario_with_provider_settings(settings, request):
    validate_generation_request(request)
    provider_config = AIProviderConfig.from_settings(settings)
    provider = provider_for_config(provider_config)
    return validate_generation_response(provider.generate(request, provider_config))
