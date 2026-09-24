from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

from core.simulation_utils import (
    clean_text as _clean_text,
    json_dict as _json_dict,
    json_list as _json_list,
)


DIRECTORY_SIMULATION_LABEL = "authorized_directory_target_sync"
VALID_DIRECTORY_PROVIDER_TYPES = {"mock_entra", "microsoft_graph"}


def _normalize_provider_type(provider_type):
    normalized = (_clean_text(provider_type) or "mock_entra").lower()
    if normalized in {"mock", "entra_mock"}:
        return "mock_entra"
    if normalized in {"graph", "ms_graph", "entra", "microsoft-graph"}:
        return "microsoft_graph"
    if normalized not in VALID_DIRECTORY_PROVIDER_TYPES:
        raise DirectoryProviderTypeError("Unsupported directory provider type: {}".format(provider_type))
    return normalized


def _normalize_group_ids(group_ids):
    values = _json_list(group_ids) if isinstance(group_ids, str) else list(group_ids or [])
    normalized = []
    for value in values:
        group_id = _clean_text(value)
        if group_id and group_id not in normalized:
            normalized.append(group_id)
    return tuple(normalized)


@dataclass(frozen=True)
class DirectoryProviderConfig:
    """UI-managed directory provider settings without OAuth token material."""

    id: int
    name: str
    provider_type: str = "mock_entra"
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    authority_url: Optional[str] = None
    client_id: Optional[str] = None
    enabled: bool = False
    consent_status: str = "not_configured"
    consented_scopes: Tuple[str, ...] = field(default_factory=tuple)
    selected_groups: Tuple[str, ...] = field(default_factory=tuple)
    field_mapping: Dict[str, str] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    secret_configured: bool = False
    secret_reference: Optional[str] = None
    last_error_message: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "name", _clean_text(self.name) or "Directory Provider")
        object.__setattr__(self, "provider_type", _normalize_provider_type(self.provider_type))
        object.__setattr__(self, "tenant_id", _clean_text(self.tenant_id))
        object.__setattr__(self, "tenant_name", _clean_text(self.tenant_name))
        object.__setattr__(self, "authority_url", _clean_text(self.authority_url))
        object.__setattr__(self, "client_id", _clean_text(self.client_id))
        object.__setattr__(self, "consent_status", (_clean_text(self.consent_status) or "not_configured").lower())
        object.__setattr__(
            self,
            "consented_scopes",
            tuple(scope for scope in (_clean_text(value) for value in self.consented_scopes) if scope),
        )
        object.__setattr__(self, "selected_groups", _normalize_group_ids(self.selected_groups))
        object.__setattr__(self, "field_mapping", dict(self.field_mapping or {}))
        object.__setattr__(self, "settings", dict(self.settings or {}))
        object.__setattr__(self, "secret_reference", _clean_text(self.secret_reference))
        object.__setattr__(self, "last_error_message", _clean_text(self.last_error_message))

    @classmethod
    def from_settings(cls, settings):
        return cls(
            id=int(settings["id"]),
            name=settings["name"],
            provider_type=settings.get("provider_type") or "mock_entra",
            tenant_id=settings.get("tenant_id"),
            tenant_name=settings.get("tenant_name"),
            authority_url=settings.get("authority_url"),
            client_id=settings.get("client_id"),
            enabled=bool(settings.get("enabled")),
            consent_status=settings.get("consent_status") or "not_configured",
            consented_scopes=tuple(_json_list(settings.get("consented_scopes") or settings.get("consented_scopes_json"))),
            selected_groups=tuple(_json_list(settings.get("selected_groups") or settings.get("selected_groups_json"))),
            field_mapping=_json_dict(settings.get("field_mapping") or settings.get("field_mapping_json")),
            settings=_json_dict(settings.get("settings") or settings.get("settings_json")),
            secret_configured=bool(settings.get("secret_configured"))
            or settings.get("secret_placeholder") == "configured",
            secret_reference=settings.get("secret_reference"),
            last_error_message=settings.get("last_error_message"),
        )


@dataclass(frozen=True)
class DirectoryGroup:
    external_group_id: str
    display_name: str
    description: Optional[str] = None
    member_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "external_group_id", _clean_text(self.external_group_id))
        object.__setattr__(self, "display_name", _clean_text(self.display_name) or self.external_group_id)
        object.__setattr__(self, "description", _clean_text(self.description))
        object.__setattr__(self, "member_count", int(self.member_count or 0))
        metadata = dict(self.metadata or {})
        metadata.setdefault("artifact_label", DIRECTORY_SIMULATION_LABEL)
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class DirectoryUser:
    external_user_id: str
    user_principal_name: str
    display_name: str
    mail: Optional[str] = None
    given_name: Optional[str] = None
    surname: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    office_location: Optional[str] = None
    mobile_phone: Optional[str] = None
    business_phones: Tuple[str, ...] = field(default_factory=tuple)
    manager: Optional[str] = None
    groups: Tuple[str, ...] = field(default_factory=tuple)
    source_group_ids: Tuple[str, ...] = field(default_factory=tuple)
    active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "external_user_id", _clean_text(self.external_user_id))
        object.__setattr__(self, "user_principal_name", _clean_text(self.user_principal_name))
        object.__setattr__(self, "display_name", _clean_text(self.display_name) or self.user_principal_name)
        object.__setattr__(self, "mail", _clean_text(self.mail))
        object.__setattr__(self, "given_name", _clean_text(self.given_name))
        object.__setattr__(self, "surname", _clean_text(self.surname))
        object.__setattr__(self, "job_title", _clean_text(self.job_title))
        object.__setattr__(self, "department", _clean_text(self.department))
        object.__setattr__(self, "office_location", _clean_text(self.office_location))
        object.__setattr__(self, "mobile_phone", _clean_text(self.mobile_phone))
        object.__setattr__(
            self,
            "business_phones",
            tuple(phone for phone in (_clean_text(value) for value in self.business_phones) if phone),
        )
        object.__setattr__(self, "manager", _clean_text(self.manager))
        object.__setattr__(self, "groups", tuple(group for group in (_clean_text(value) for value in self.groups) if group))
        object.__setattr__(self, "source_group_ids", _normalize_group_ids(self.source_group_ids))
        metadata = dict(self.metadata or {})
        metadata.setdefault("artifact_label", DIRECTORY_SIMULATION_LABEL)
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class DirectorySyncResult:
    provider_id: int
    selected_group_ids: Tuple[str, ...]
    groups: Tuple[DirectoryGroup, ...]
    users: Tuple[DirectoryUser, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        metadata = dict(self.metadata or {})
        metadata.setdefault("artifact_label", DIRECTORY_SIMULATION_LABEL)
        object.__setattr__(self, "selected_group_ids", _normalize_group_ids(self.selected_group_ids))
        object.__setattr__(self, "groups", tuple(self.groups or ()))
        object.__setattr__(self, "users", tuple(self.users or ()))
        object.__setattr__(self, "metadata", metadata)


@runtime_checkable
class DirectoryConnector(Protocol):
    provider_type: str

    def list_groups(self, provider_config: DirectoryProviderConfig) -> Sequence[DirectoryGroup]:
        """List groups available through a UI-managed directory provider."""

    def preview_users(
        self,
        provider_config: DirectoryProviderConfig,
        group_ids: Optional[Sequence[str]] = None,
    ) -> DirectorySyncResult:
        """Return users that would be staged for the selected groups."""

    def sync_staged_users(
        self,
        provider_config: DirectoryProviderConfig,
        group_ids: Optional[Sequence[str]] = None,
    ) -> DirectorySyncResult:
        """Return users ready for the staging table without importing targets."""

    def map_user_to_target(self, user: DirectoryUser, provider_config: DirectoryProviderConfig) -> Dict[str, Any]:
        """Map a directory user into the simulation target payload shape."""


class DirectoryConnectorError(Exception):
    """Base error for directory connector failures."""


class DirectoryDisabledProviderError(DirectoryConnectorError):
    """Raised when a disabled directory provider is selected."""


class DirectoryProviderConfigurationError(DirectoryConnectorError):
    """Raised when provider settings are incomplete or unavailable."""


class DirectoryProviderTypeError(DirectoryConnectorError):
    """Raised when no connector exists for a configured provider type."""


def _require_enabled(provider_config):
    if not provider_config.enabled:
        raise DirectoryDisabledProviderError("Directory provider '{}' is disabled.".format(provider_config.name))


def _default_target_payload(user):
    return {
        "name": user.display_name,
        "display_name": user.display_name,
        "email": user.mail or user.user_principal_name,
        "phone": user.mobile_phone or (user.business_phones[0] if user.business_phones else None),
        "department": user.department,
        "manager": user.manager,
        "source": "directory",
        "active": user.active,
        "channel": "email" if (user.mail or user.user_principal_name) else "sms",
    }


def _mapped_value(user, source_field):
    if source_field in {"phone", "mobile_phone"}:
        return user.mobile_phone or (user.business_phones[0] if user.business_phones else None)
    return getattr(user, source_field, None)


class BaseDirectoryConnector:
    provider_type = None

    def _selected_group_ids(self, provider_config, group_ids=None):
        selected = _normalize_group_ids(group_ids)
        return selected or provider_config.selected_groups

    def map_user_to_target(self, user, provider_config):
        payload = _default_target_payload(user)
        for target_field, source_field in provider_config.field_mapping.items():
            clean_target = _clean_text(target_field)
            clean_source = _clean_text(source_field)
            if clean_target and clean_source:
                payload[clean_target] = _mapped_value(user, clean_source)
        payload["source"] = "directory"
        return payload


class MockEntraDirectoryConnector(BaseDirectoryConnector):
    """Deterministic offline Microsoft Entra-like connector for development."""

    provider_type = "mock_entra"

    _groups = (
        DirectoryGroup(
            external_group_id="group-finance",
            display_name="Finance Awareness Pilot",
            description="Mock Entra group for finance training targets.",
            member_count=2,
        ),
        DirectoryGroup(
            external_group_id="group-engineering",
            display_name="Engineering Awareness Pilot",
            description="Mock Entra group for engineering training targets.",
            member_count=2,
        ),
        DirectoryGroup(
            external_group_id="group-operations",
            display_name="Operations Awareness Pilot",
            description="Mock Entra group for operations training targets.",
            member_count=1,
        ),
    )
    _users = (
        DirectoryUser(
            external_user_id="mock-user-avery-stone",
            user_principal_name="avery.stone@example.test",
            mail="avery.stone@example.test",
            display_name="Avery Stone",
            given_name="Avery",
            surname="Stone",
            job_title="Finance Manager",
            department="Finance",
            office_location="HQ-4",
            mobile_phone="+15550101001",
            business_phones=("+15550101011",),
            manager="Pat Morgan",
            groups=("Finance Awareness Pilot",),
            source_group_ids=("group-finance",),
        ),
        DirectoryUser(
            external_user_id="mock-user-riley-chen",
            user_principal_name="riley.chen@example.test",
            mail="riley.chen@example.test",
            display_name="Riley Chen",
            given_name="Riley",
            surname="Chen",
            job_title="Engineer",
            department="Engineering",
            office_location="Remote",
            mobile_phone="+15550101004",
            manager="Jordan Lee",
            groups=("Engineering Awareness Pilot",),
            source_group_ids=("group-engineering",),
        ),
        DirectoryUser(
            external_user_id="mock-user-jordan-lee",
            user_principal_name="jordan.lee@example.test",
            mail="jordan.lee@example.test",
            display_name="Jordan Lee",
            given_name="Jordan",
            surname="Lee",
            job_title="Operations Lead",
            department="Operations",
            office_location="HQ-2",
            mobile_phone="+15550101002",
            manager="Pat Morgan",
            groups=("Operations Awareness Pilot",),
            source_group_ids=("group-operations",),
        ),
        DirectoryUser(
            external_user_id="mock-user-morgan-patel",
            user_principal_name="morgan.patel@example.test",
            mail="morgan.patel@example.test",
            display_name="Morgan Patel",
            given_name="Morgan",
            surname="Patel",
            job_title="Security Champion",
            department="Engineering",
            office_location="HQ-3",
            mobile_phone="+15550101003",
            manager="Avery Stone",
            groups=("Engineering Awareness Pilot", "Finance Awareness Pilot"),
            source_group_ids=("group-engineering", "group-finance"),
        ),
    )

    def list_groups(self, provider_config):
        _require_enabled(provider_config)
        return list(self._groups)

    def preview_users(self, provider_config, group_ids=None):
        _require_enabled(provider_config)
        selected = self._selected_group_ids(provider_config, group_ids)
        groups = tuple(group for group in self._groups if not selected or group.external_group_id in selected)
        selected_set = set(selected)
        users = tuple(
            user
            for user in self._users
            if not selected_set or selected_set.intersection(user.source_group_ids)
        )
        return DirectorySyncResult(
            provider_id=provider_config.id,
            selected_group_ids=selected,
            groups=groups,
            users=users,
            metadata={
                "artifact_label": DIRECTORY_SIMULATION_LABEL,
                "mock": True,
                "external_directory": False,
            },
        )

    def sync_staged_users(self, provider_config, group_ids=None):
        return self.preview_users(provider_config, group_ids=group_ids)


class MicrosoftGraphDirectoryConnector(BaseDirectoryConnector):
    """Configuration-ready Microsoft Graph shell with no network side effects."""

    provider_type = "microsoft_graph"
    required_scopes = ("Group.Read.All", "User.Read.All")

    def _validate_config(self, provider_config):
        _require_enabled(provider_config)
        missing = []
        for attr, label in (
            ("tenant_id", "tenant_id"),
            ("client_id", "client_id"),
            ("authority_url", "authority_url"),
        ):
            if not _clean_text(getattr(provider_config, attr)):
                missing.append(label)
        if missing:
            raise DirectoryProviderConfigurationError(
                "Microsoft Graph directory provider '{}' is missing required settings: {}.".format(
                    provider_config.name,
                    ", ".join(missing),
                )
            )
        missing_scopes = [scope for scope in self.required_scopes if scope not in provider_config.consented_scopes]
        if missing_scopes:
            raise DirectoryProviderConfigurationError(
                "Microsoft Graph directory provider '{}' needs consent for: {}.".format(
                    provider_config.name,
                    ", ".join(missing_scopes),
                )
            )

    def build_group_request(self, provider_config):
        self._validate_config(provider_config)
        return {
            "method": "GET",
            "url": "https://graph.microsoft.com/v1.0/groups",
            "tenant_id": provider_config.tenant_id,
            "client_id": provider_config.client_id,
            "scopes": list(self.required_scopes),
            "metadata": {"artifact_label": DIRECTORY_SIMULATION_LABEL},
        }

    def list_groups(self, provider_config):
        self.build_group_request(provider_config)
        raise DirectoryProviderConfigurationError(
            "Microsoft Graph group listing is not enabled until UI-managed credential retrieval is implemented."
        )

    def preview_users(self, provider_config, group_ids=None):
        self.build_group_request(provider_config)
        raise DirectoryProviderConfigurationError(
            "Microsoft Graph user preview is not enabled until UI-managed credential retrieval is implemented."
        )

    def sync_staged_users(self, provider_config, group_ids=None):
        return self.preview_users(provider_config, group_ids=group_ids)


def connector_for_config(provider_config):
    provider_type = _normalize_provider_type(provider_config.provider_type)
    if provider_type == "mock_entra":
        return MockEntraDirectoryConnector()
    if provider_type == "microsoft_graph":
        return MicrosoftGraphDirectoryConnector()
    raise DirectoryProviderTypeError("Unsupported directory provider type: {}".format(provider_config.provider_type))


def connector_for_provider_settings(settings):
    provider_config = DirectoryProviderConfig.from_settings(settings)
    return connector_for_config(provider_config)


def list_groups_with_provider_settings(settings):
    provider_config = DirectoryProviderConfig.from_settings(settings)
    return connector_for_config(provider_config).list_groups(provider_config)


def preview_users_with_provider_settings(settings, group_ids=None):
    provider_config = DirectoryProviderConfig.from_settings(settings)
    return connector_for_config(provider_config).preview_users(provider_config, group_ids=group_ids)


def sync_staged_users_with_provider_settings(settings, group_ids=None):
    provider_config = DirectoryProviderConfig.from_settings(settings)
    return connector_for_config(provider_config).sync_staged_users(provider_config, group_ids=group_ids)


def map_user_to_target_with_provider_settings(settings, user):
    provider_config = DirectoryProviderConfig.from_settings(settings)
    return connector_for_config(provider_config).map_user_to_target(user, provider_config)
