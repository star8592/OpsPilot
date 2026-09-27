from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opspilot.config import load_project
from opspilot.core import OpsPilotError
from opspilot.runtime import json_pointer, verify_runtime

HEALTH = {
    "status": "ok",
    "build": {"revision": "abcdef0", "schema_digest": "a" * 64},
    "readiness": {
        "public_login": True,
        "providers": {"email": True, "google": True},
    },
}

CONTRACT = {
    "base_url": "https://staging.example.test",
    "health_path": "/healthz",
    "revision_pointer": "/build/revision",
    "schema_digest_pointer": "/build/schema_digest",
    "checks": [
        {"name": "public_login_ready", "pointer": "/readiness/public_login", "equals": True},
        {"name": "email_ready", "pointer": "/readiness/providers/email", "equals": True},
        {"name": "google_ready", "pointer": "/readiness/providers/google", "equals": True},
    ],
}


class ConfigRuntimeTests(unittest.TestCase):
    def test_json_pointer(self):
        self.assertTrue(json_pointer(HEALTH, "/readiness/providers/email"))
        with self.assertRaisesRegex(OpsPilotError, "missing JSON pointer"):
            json_pointer(HEALTH, "/readiness/providers/github")

    @patch("opspilot.runtime.fetch_health", return_value=HEALTH)
    def test_runtime_contract(self, _fetch):
        result = verify_runtime(
            environment="staging",
            contract=CONTRACT,
            expected_revision="abcdef0",
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["revision"], "abcdef0")
        self.assertEqual(result["schema_digest"], "a" * 64)
        self.assertTrue(result["checks"]["google_ready"])

    @patch("opspilot.runtime.fetch_health", return_value=HEALTH)
    def test_runtime_revision_drift_fails_closed(self, _fetch):
        with self.assertRaisesRegex(OpsPilotError, "runtime revision mismatch"):
            verify_runtime(environment="staging", contract=CONTRACT, expected_revision="wrong")

    def test_config_cannot_downgrade_production_action(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "project.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "x"},
                        "adapters": {
                            "promote": {
                                "environment": "staging",
                                "command": ["true"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OpsPilotError, "environment='production'"):
                load_project(path)

    def test_candidate_required_checks_must_be_declared(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "project.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "x"},
                        "environments": {"staging": {"runtime": CONTRACT}},
                        "policy": {
                            "candidate": {
                                "require_runtime_verification": "staging",
                                "required_runtime_checks": ["missing_check"],
                            }
                        },
                        "adapters": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OpsPilotError, "undeclared"):
                load_project(path)


if __name__ == "__main__":
    unittest.main()
