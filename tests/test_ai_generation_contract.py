import unittest
import sqlite3
import tempfile
from pathlib import Path

from core.ai_generation import (
    AI_GENERATION_LABEL,
    AIDisabledProviderError,
    AIProviderConfigurationError,
    AIGeneratedDraft,
    AIGenerationResponse,
    AIProviderConfig,
    AIScenarioProvider,
    AIScenarioRequest,
    LocalHTTPModelServerProvider,
    LocalMockScenarioProvider,
    OpenAICompatibleHTTPProvider,
    generate_scenario_with_provider_settings,
    provider_for_config,
)
from core.db_migration import migrate_db
from core.simulation_service import generate_ai_scenario, update_ai_provider_settings


class ContractProvider:
    provider_type = "local"

    def generate(self, request, provider_config):
        return AIGenerationResponse(
            provider_id=provider_config.id,
            provider_name=provider_config.name,
            provider_type=provider_config.provider_type,
            model_name=provider_config.model_name,
            channels=tuple(request.channels),
            draft=AIGeneratedDraft(
                email_subject="Authorized training reminder",
                email_body="This is a security awareness training simulation.",
                sms_body="Security awareness training reminder.",
                voice_script="Hello. This is an authorized training simulation.",
                landing_text="Review the training lesson.",
                training_text="Pause and verify requests before acting.",
            ),
            risk_flags=["training_label_present"],
            safety_notes=["Generated for authorized awareness training only."],
        )


class AIGenerationContractTest(unittest.TestCase):
    def test_request_normalizes_required_generation_context(self):
        request = AIScenarioRequest(
            scenario_goal="  Reduce unsafe link clicks  ",
            audience=" Finance team ",
            channels=["email", "sms", "email"],
            tone="plainspoken",
            difficulty="STANDARD",
            safety_constraints=[" No credential collection ", ""],
            campaign_context={"campaign_id": 42},
        )

        self.assertEqual(request.scenario_goal, "Reduce unsafe link clicks")
        self.assertEqual(request.audience, "Finance team")
        self.assertEqual(request.channels, ("email", "sms"))
        self.assertEqual(request.difficulty, "standard")
        self.assertEqual(request.safety_constraints, ("No credential collection",))
        self.assertEqual(request.requested_channels(), {"email", "sms"})

    def test_request_rejects_missing_context_and_unknown_channels(self):
        with self.assertRaisesRegex(ValueError, "goal is required"):
            AIScenarioRequest("", "Finance", ["email"])

        with self.assertRaisesRegex(ValueError, "channel must be one of"):
            AIScenarioRequest("Training goal", "Finance", ["chat"])

        with self.assertRaisesRegex(ValueError, "difficulty must be one of"):
            AIScenarioRequest("Training goal", "Finance", ["email"], difficulty="expert")

    def test_response_and_draft_metadata_are_labeled_for_authorized_training(self):
        response = AIGenerationResponse(
            provider_id=1,
            provider_name="Local Demo Provider",
            provider_type="local",
            model_name="local-simulation-model",
            channels=("voice",),
            draft=AIGeneratedDraft(voice_script="Authorized training call script."),
        )

        self.assertEqual(response.metadata["artifact_label"], AI_GENERATION_LABEL)
        self.assertEqual(response.draft.metadata["artifact_label"], AI_GENERATION_LABEL)
        self.assertEqual(response.channels, ("voice",))

    def test_provider_config_uses_ui_settings_without_secret_material(self):
        provider = AIProviderConfig.from_settings({
            "id": 7,
            "name": "Cloud Demo Provider",
            "provider_type": "cloud",
            "model_name": "cloud-awareness-model",
            "base_url": "https://api.example.test/v1",
            "enabled": 0,
            "secret_configured": True,
            "description": "Configured through the UI.",
        })

        self.assertEqual(provider.id, 7)
        self.assertFalse(provider.enabled)
        self.assertTrue(provider.secret_configured)
        self.assertFalse(hasattr(provider, "secret"))

    def test_provider_protocol_returns_contract_response(self):
        provider = ContractProvider()
        request = AIScenarioRequest(
            scenario_goal="Reinforce reporting suspicious messages",
            audience="Operations staff",
            channels=["email", "sms", "voice"],
        )
        provider_config = AIProviderConfig(
            id=1,
            name="Local Demo Provider",
            provider_type="local",
            model_name="local-simulation-model",
            enabled=True,
        )

        self.assertIsInstance(provider, AIScenarioProvider)
        response = provider.generate(request, provider_config)

        self.assertEqual(response.provider_id, 1)
        self.assertEqual(response.channels, ("email", "sms", "voice"))
        self.assertEqual(response.draft.email_subject, "Authorized training reminder")
        self.assertIn("training_label_present", response.risk_flags)

    def test_local_mock_provider_generates_deterministic_channel_drafts(self):
        provider = LocalMockScenarioProvider()
        request = AIScenarioRequest(
            scenario_goal="Reinforce reporting suspicious messages",
            audience="Finance team",
            channels=["email", "sms", "voice"],
            tone="calm",
            difficulty="introductory",
            training_reminder="Use the report button when something feels unusual.",
        )
        provider_config = AIProviderConfig(
            id=3,
            name="Local Demo Provider",
            provider_type="local",
            model_name="local-simulation-model",
            enabled=True,
        )

        first = provider.generate(request, provider_config)
        second = provider.generate(request, provider_config)

        self.assertEqual(first, second)
        self.assertIn("Training simulation", first.draft.email_subject)
        self.assertIn("Authorized training simulation", first.draft.sms_body)
        self.assertIn("authorized security awareness training simulation", first.draft.voice_script.lower())
        self.assertIn("credential_collection_disallowed", first.risk_flags)
        self.assertEqual(first.metadata["artifact_label"], AI_GENERATION_LABEL)

    def test_disabled_provider_cannot_generate(self):
        request = AIScenarioRequest("Improve reporting", "Operations", ["email"])
        provider_config = AIProviderConfig(
            id=4,
            name="Disabled Local Provider",
            provider_type="local",
            model_name="local-simulation-model",
            enabled=False,
        )

        with self.assertRaisesRegex(AIDisabledProviderError, "disabled"):
            LocalMockScenarioProvider().generate(request, provider_config)

    def test_http_provider_shells_validate_ui_managed_configuration(self):
        request = AIScenarioRequest("Reduce unsafe clicks", "Support", ["email"])
        cloud_config = AIProviderConfig(
            id=5,
            name="Cloud Provider",
            provider_type="cloud",
            model_name="awareness-gpt",
            base_url="https://api.example.test/v1",
            enabled=True,
            secret_configured=True,
        )
        local_http_config = AIProviderConfig(
            id=6,
            name="Local HTTP Provider",
            provider_type="local_http",
            model_name="awareness-local",
            base_url="http://localhost:11434",
            enabled=True,
        )

        cloud_payload = OpenAICompatibleHTTPProvider().build_payload(request, cloud_config)
        local_payload = LocalHTTPModelServerProvider().build_payload(request, local_http_config)

        self.assertEqual(cloud_payload["model"], "awareness-gpt")
        self.assertEqual(cloud_payload["response_format"], {"type": "json_object"})
        self.assertIn("messages", cloud_payload)
        self.assertNotIn("secret", str(cloud_payload).lower())
        self.assertEqual(local_payload["model"], "awareness-local")
        self.assertFalse(local_payload["stream"])
        self.assertNotIn("api_key", str(local_payload).lower())

        missing_secret_config = AIProviderConfig(
            id=7,
            name="Cloud Provider",
            provider_type="cloud",
            model_name="awareness-gpt",
            base_url="https://api.example.test/v1",
            enabled=True,
            secret_configured=False,
        )
        with self.assertRaisesRegex(AIProviderConfigurationError, "credentials configured"):
            OpenAICompatibleHTTPProvider().build_payload(request, missing_secret_config)

    def test_provider_resolver_supports_configured_provider_shapes(self):
        self.assertIsInstance(
            provider_for_config(AIProviderConfig(1, "Mock", "local", "model", enabled=True)),
            LocalMockScenarioProvider,
        )
        self.assertIsInstance(
            provider_for_config(AIProviderConfig(2, "Cloud", "openai_compatible", "model", enabled=True)),
            OpenAICompatibleHTTPProvider,
        )
        self.assertIsInstance(
            provider_for_config(AIProviderConfig(3, "Local HTTP", "local_http", "model", enabled=True)),
            LocalHTTPModelServerProvider,
        )

    def test_generation_reads_provider_settings_from_database_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "ai-generation.db")
            migrate_db(db_path)
            conn = sqlite3.connect(db_path)
            try:
                provider_id = conn.execute(
                    "SELECT id FROM ai_provider_configs WHERE provider_type = 'local'"
                ).fetchone()[0]
                request = AIScenarioRequest("Practice safe link review", "Engineering", ["email"])
                response = generate_ai_scenario(conn, provider_id, request)

                self.assertEqual(response.provider_type, "local")
                self.assertIn("Practice safe link review", response.draft.email_subject)
                self.assertNotIn("secret_placeholder", str(response))

                disabled = update_ai_provider_settings(conn, provider_id, enabled=False)
                with self.assertRaisesRegex(AIDisabledProviderError, "disabled"):
                    generate_scenario_with_provider_settings(disabled, request)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
