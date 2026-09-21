from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable


AI_GENERATION_LABEL = "authorized_security_awareness_training"
VALID_AI_CHANNELS = {"email", "sms", "voice"}
VALID_AI_DIFFICULTIES = {"introductory", "standard", "advanced"}


def _clean_text(value):
    normalized = str(value or "").strip()
    return normalized or None


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
