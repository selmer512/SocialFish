import unittest

from core.simulation_utils import (
    db_bool,
    json_dict,
    json_list,
    redact_sensitive_value,
    row_to_dict,
    rows_to_dicts,
    select_enabled_provider,
)


class FakeCursor:
    description = (("id",), ("name",))

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class SimulationUtilsTests(unittest.TestCase):
    def test_json_helpers_accept_native_and_serialized_values(self):
        self.assertEqual(json_dict('{"a": 1}'), {"a": 1})
        self.assertEqual(json_dict({"b": 2}), {"b": 2})
        self.assertEqual(json_dict("[1, 2]"), {})
        self.assertEqual(json_list('["email", "sms"]'), ["email", "sms"])
        self.assertEqual(json_list(("voice",)), ["voice"])
        self.assertEqual(json_list('{"not": "a list"}'), [])

    def test_database_row_helpers_preserve_column_names(self):
        self.assertEqual(row_to_dict(FakeCursor([(1, "Campaign")]))["name"], "Campaign")
        self.assertEqual(rows_to_dicts(FakeCursor([(1, "A"), (2, "B")])), [
            {"id": 1, "name": "A"},
            {"id": 2, "name": "B"},
        ])
        self.assertTrue(db_bool(1))
        self.assertFalse(db_bool(None))

    def test_redaction_recurses_but_preserves_safe_references(self):
        redacted = redact_sensitive_value({
            "api_key": "secret",
            "secret_reference": "vault://key",
            "nested": [{"password": "secret"}],
        }, "[REDACTED]")
        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["secret_reference"], "vault://key")
        self.assertEqual(redacted["nested"][0]["password"], "[REDACTED]")

    def test_select_enabled_provider_prefers_matching_type_then_falls_back(self):
        providers = [
            {"provider_name": "Disabled Dry Run", "provider_type": "dry_run", "enabled": False},
            {"provider_name": "Provider API", "provider_type": "api", "enabled": True},
            {"provider_name": "Dry Run", "provider_type": "dry_run", "enabled": True},
        ]
        self.assertEqual(select_enabled_provider(providers, "dry_run")["provider_name"], "Dry Run")
        self.assertEqual(select_enabled_provider(providers, "smtp")["provider_name"], "Provider API")
        self.assertIsNone(select_enabled_provider([{"provider_type": "api", "enabled": False}]))


if __name__ == "__main__":
    unittest.main()
