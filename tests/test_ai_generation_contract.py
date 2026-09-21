import unittest

from core.ai_generation import (
    AI_GENERATION_LABEL,
    AIGeneratedDraft,
    AIGenerationResponse,
    AIProviderConfig,
    AIScenarioProvider,
    AIScenarioRequest,
)


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


if __name__ == "__main__":
    unittest.main()
