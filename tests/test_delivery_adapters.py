import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_migration import migrate_db
from core.delivery_adapters import (
    DELIVERY_SIMULATION_LABEL,
    DeliveryAttemptRequest,
    DeliveryDisabledProviderError,
    DeliveryMessage,
    DeliveryProviderConfig,
    DeliveryProviderConfigurationError,
    DeliveryRecipient,
    EmailAPIDeliveryAdapter,
    SMSAPIDeliveryAdapter,
    SMTPEmailDeliveryAdapter,
    VoiceAPIDeliveryAdapter,
    provider_for_config,
    send_with_provider_settings,
)
from core.simulation_service import (
    list_delivery_provider_settings,
    update_delivery_provider_settings,
)


class DeliveryAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "delivery-adapters.db")
        migrate_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _request(self, channel):
        recipient = DeliveryRecipient(
            target_id=42,
            name="Taylor Gray",
            email="taylor.gray@example.test",
            phone="+15550102222",
        )
        return DeliveryAttemptRequest(
            campaign_id=7,
            target_id=42,
            channel=channel,
            message=DeliveryMessage(
                channel=channel,
                subject="Authorized training simulation",
                body="This is an authorized security awareness training simulation.",
            ),
            recipient=recipient,
            delivery_job_id=3,
            attempt_id=9,
        )

    def _provider(self, provider_key):
        return next(
            provider
            for provider in list_delivery_provider_settings(self.conn)
            if provider["provider_key"] == provider_key
        )

    def test_dry_run_adapters_return_simulated_delivery_results_without_network(self):
        cases = [
            ("dry_run_email", "email"),
            ("dry_run_sms", "sms"),
            ("dry_run_voice", "voice"),
        ]

        for provider_key, channel in cases:
            provider = self._provider(provider_key)
            result = send_with_provider_settings(provider, self._request(channel))

            self.assertEqual(result.status, "delivered")
            self.assertEqual(result.event_type, "delivered")
            self.assertEqual(result.provider, provider_key)
            self.assertTrue(result.provider_response["dry_run"])
            self.assertFalse(result.provider_response["external_delivery"])
            self.assertEqual(result.event_metadata["artifact_label"], DELIVERY_SIMULATION_LABEL)
            self.assertEqual(result.event_metadata["provider_id"], provider["id"])

    def test_voice_dry_run_records_simulated_response_metadata(self):
        result = send_with_provider_settings(
            self._provider("dry_run_voice"),
            self._request("voice"),
        )

        self.assertEqual(result.provider_response["simulated_voice_response"], "completed_training")
        self.assertEqual(result.event_metadata["voice_response"], "completed_training")

    def test_real_provider_shells_refuse_disabled_or_incomplete_execution(self):
        smtp_provider = DeliveryProviderConfig.from_settings(self._provider("smtp_email"))

        with self.assertRaisesRegex(DeliveryDisabledProviderError, "disabled"):
            SMTPEmailDeliveryAdapter().build_payload(self._request("email"), smtp_provider)

        enabled_smtp = update_delivery_provider_settings(
            self.conn,
            smtp_provider.id,
            enabled=True,
            settings={
                "smtp_host": "smtp.example.test",
                "from_email": "training@example.test",
            },
        )
        with self.assertRaisesRegex(DeliveryProviderConfigurationError, "smtp_port"):
            SMTPEmailDeliveryAdapter().build_payload(
                self._request("email"),
                DeliveryProviderConfig.from_settings(enabled_smtp),
            )

    def test_real_provider_shells_build_payloads_only_after_required_settings_and_secret(self):
        api_provider = self._provider("email_api")
        enabled_api = update_delivery_provider_settings(
            self.conn,
            api_provider["id"],
            enabled=True,
            settings={"api_key": "stored-by-ui", "from_email": "training@example.test"},
        )

        with self.assertRaisesRegex(DeliveryProviderConfigurationError, "credentials configured"):
            EmailAPIDeliveryAdapter().build_payload(
                self._request("email"),
                DeliveryProviderConfig.from_settings(enabled_api),
            )

        configured_api = update_delivery_provider_settings(
            self.conn,
            api_provider["id"],
            secret="do-not-return-this-secret",
        )
        payload = EmailAPIDeliveryAdapter().build_payload(
            self._request("email"),
            DeliveryProviderConfig.from_settings(configured_api),
        )

        self.assertEqual(payload["from_email"], "training@example.test")
        self.assertEqual(payload["recipient"], "taylor.gray@example.test")
        self.assertNotIn("do-not-return-this-secret", str(configured_api))
        self.assertNotIn("secret_placeholder", configured_api)

    def test_provider_resolver_supports_configured_delivery_shapes(self):
        providers = {
            provider["provider_key"]: DeliveryProviderConfig.from_settings(provider)
            for provider in list_delivery_provider_settings(self.conn)
        }

        self.assertEqual(provider_for_config(providers["dry_run_email"]).channel, "email")
        self.assertEqual(provider_for_config(providers["dry_run_sms"]).channel, "sms")
        self.assertEqual(provider_for_config(providers["dry_run_voice"]).channel, "voice")
        self.assertIsInstance(provider_for_config(providers["smtp_email"]), SMTPEmailDeliveryAdapter)
        self.assertIsInstance(provider_for_config(providers["email_api"]), EmailAPIDeliveryAdapter)
        self.assertIsInstance(provider_for_config(providers["sms_api"]), SMSAPIDeliveryAdapter)
        self.assertIsInstance(provider_for_config(providers["voice_api"]), VoiceAPIDeliveryAdapter)


if __name__ == "__main__":
    unittest.main()
