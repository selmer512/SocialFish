import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_migration import migrate_db
from core.directory_connectors import (
    DirectoryDisabledProviderError,
    DirectoryProviderConfig,
    DirectoryProviderConfigurationError,
    MicrosoftGraphDirectoryConnector,
    MockEntraDirectoryConnector,
    connector_for_provider_settings,
)
from core.simulation_service import (
    create_directory_provider_settings,
    list_directory_groups,
    list_directory_provider_settings,
    map_directory_user_to_target,
    preview_directory_users,
    sync_directory_staged_users,
    update_directory_provider_settings,
)


class DirectoryConnectorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "directory-connectors.db")
        migrate_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_mock_entra_lists_groups_and_previews_deterministic_users(self):
        provider = create_directory_provider_settings(
            self.conn,
            "Mock Entra",
            provider_type="mock_entra",
            enabled=True,
            consent_status="granted",
            selected_groups=["group-finance"],
        )

        groups = list_directory_groups(self.conn, provider["id"])
        preview = preview_directory_users(self.conn, provider["id"])
        sync_result = sync_directory_staged_users(self.conn, provider["id"], group_ids=["group-engineering"])

        self.assertEqual(type(connector_for_provider_settings(provider)), MockEntraDirectoryConnector)
        self.assertEqual(
            [group.external_group_id for group in groups],
            ["group-finance", "group-engineering", "group-operations"],
        )
        self.assertEqual(preview.selected_group_ids, ("group-finance",))
        self.assertEqual(
            [user.external_user_id for user in preview.users],
            ["mock-user-avery-stone", "mock-user-morgan-patel"],
        )
        self.assertEqual(sync_result.selected_group_ids, ("group-engineering",))
        self.assertEqual(
            [user.external_user_id for user in sync_result.users],
            ["mock-user-riley-chen", "mock-user-morgan-patel"],
        )
        self.assertTrue(preview.metadata["mock"])
        self.assertFalse(preview.metadata["external_directory"])

    def test_disabled_directory_provider_fails_before_listing_groups(self):
        provider = create_directory_provider_settings(
            self.conn,
            "Disabled Mock Entra",
            provider_type="mock_entra",
            enabled=False,
        )

        with self.assertRaisesRegex(DirectoryDisabledProviderError, "disabled"):
            list_directory_groups(self.conn, provider["id"])

    def test_directory_user_mapping_uses_provider_field_mapping(self):
        provider = create_directory_provider_settings(
            self.conn,
            "Mapped Mock Entra",
            provider_type="mock_entra",
            enabled=True,
            selected_groups=["group-operations"],
            field_mapping={
                "name": "display_name",
                "phone": "mobile_phone",
                "manager": "manager",
            },
        )
        preview = preview_directory_users(self.conn, provider["id"])
        payload = map_directory_user_to_target(self.conn, provider["id"], preview.users[0])

        self.assertEqual(payload["name"], "Jordan Lee")
        self.assertEqual(payload["display_name"], "Jordan Lee")
        self.assertEqual(payload["email"], "jordan.lee@example.test")
        self.assertEqual(payload["phone"], "+15550101002")
        self.assertEqual(payload["department"], "Operations")
        self.assertEqual(payload["manager"], "Pat Morgan")
        self.assertEqual(payload["source"], "directory")
        self.assertEqual(payload["channel"], "email")

    def test_provider_settings_redact_secret_and_drive_connector_selection(self):
        provider = create_directory_provider_settings(
            self.conn,
            "Graph Shell",
            provider_type="microsoft_graph",
            tenant_id="tenant-123",
            tenant_name="Example Tenant",
            authority_url="https://login.microsoftonline.com/tenant-123",
            client_id="client-123",
            enabled=True,
            consent_status="granted",
            consented_scopes=["Group.Read.All", "User.Read.All"],
            secret_reference="vault://directory/graph-shell",
            secret="do-not-return-this-secret",
        )
        listed = list_directory_provider_settings(self.conn)[0]

        self.assertEqual(type(connector_for_provider_settings(provider)), MicrosoftGraphDirectoryConnector)
        self.assertTrue(listed["secret_configured"])
        self.assertEqual(listed["secret_reference"], "vault://directory/graph-shell")
        self.assertNotIn("secret_placeholder", listed)
        self.assertNotIn("do-not-return-this-secret", str(listed))

    def test_microsoft_graph_shell_validates_settings_without_network(self):
        provider = create_directory_provider_settings(
            self.conn,
            "Incomplete Graph Shell",
            provider_type="microsoft_graph",
            enabled=True,
        )

        with self.assertRaisesRegex(DirectoryProviderConfigurationError, "tenant_id"):
            list_directory_groups(self.conn, provider["id"])

        configured = update_directory_provider_settings(
            self.conn,
            provider["id"],
            tenant_id="tenant-123",
            authority_url="https://login.microsoftonline.com/tenant-123",
            client_id="client-123",
            consent_status="granted",
            consented_scopes=["Group.Read.All", "User.Read.All"],
        )
        request = MicrosoftGraphDirectoryConnector().build_group_request(
            DirectoryProviderConfig.from_settings(configured)
        )

        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["url"], "https://graph.microsoft.com/v1.0/groups")
        self.assertEqual(request["tenant_id"], "tenant-123")
        self.assertEqual(request["scopes"], ["Group.Read.All", "User.Read.All"])
        with self.assertRaisesRegex(DirectoryProviderConfigurationError, "credential retrieval"):
            list_directory_groups(self.conn, provider["id"])


if __name__ == "__main__":
    unittest.main()
