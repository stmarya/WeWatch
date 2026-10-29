import unittest

from utils.deployment_security import (
    validate_dashboard_config,
    validate_signaling_config,
)
from utils.privacy import RETENTION_ENV_VARS, validate_production_privacy


class DeploymentSecurityTests(unittest.TestCase):
    def test_development_dashboard_must_remain_loopback(self):
        validate_dashboard_config(
            environment="development",
            host="127.0.0.1",
            cookie_secure=False,
            session_secret="s" * 40,
            privacy_acknowledged=False,
        )
        with self.assertRaises(RuntimeError):
            validate_dashboard_config(
                environment="development",
                host="0.0.0.0",
                cookie_secure=False,
                session_secret="s" * 40,
                privacy_acknowledged=False,
            )

    def test_production_requires_secure_sessions_and_privacy_ack(self):
        with self.assertRaises(RuntimeError):
            validate_dashboard_config(
                environment="production",
                host="0.0.0.0",
                cookie_secure=False,
                session_secret="s" * 40,
                privacy_acknowledged=True,
            )
        with self.assertRaises(RuntimeError):
            validate_dashboard_config(
                environment="production",
                host="0.0.0.0",
                cookie_secure=True,
                session_secret="s" * 40,
                privacy_acknowledged=False,
            )

    def test_signaling_production_requires_token_and_distinct_secrets(self):
        validate_signaling_config(
            environment="production",
            host="0.0.0.0",
            allow_unsafe_werkzeug=False,
            require_join_token=True,
            admin_token="a" * 40,
            signing_secret="b" * 40,
        )
        with self.assertRaises(RuntimeError):
            validate_signaling_config(
                environment="production",
                host="0.0.0.0",
                allow_unsafe_werkzeug=True,
                require_join_token=True,
                admin_token="a" * 40,
                signing_secret="b" * 40,
            )

    def test_production_requires_explicit_retention_for_every_data_type(self):
        retention = {name: 30 for name in RETENTION_ENV_VARS}
        validate_production_privacy(
            environment="production",
            privacy_acknowledged=True,
            retention=retention,
        )
        retention[RETENTION_ENV_VARS[0]] = 0
        with self.assertRaises(RuntimeError):
            validate_production_privacy(
                environment="production",
                privacy_acknowledged=True,
                retention=retention,
            )


if __name__ == "__main__":
    unittest.main()