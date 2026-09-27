from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from opspilot.core import OpsPilotError
from opspilot.executor import run_adapter
from opspilot.release import verify_signed_manifest


class ReleaseExecutorTests(unittest.TestCase):
    def test_adapter_evidence_hashes_output(self):
        result = run_adapter(
            action="validate",
            adapter={
                "environment": "ci",
                "command": ["python3", "-c", "print('secret-like-output')"],
            },
            project_id="x",
            release="v1",
            revision="abc",
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("stdout_sha256", result)
        self.assertNotIn("stdout", result)

    def test_dry_run_does_not_execute(self):
        result = run_adapter(
            action="deploy-staging",
            adapter={"environment": "staging", "command": ["false"]},
            project_id="x",
            release="v1",
            revision=None,
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])

    def test_signed_manifest_binds_release_revision_and_component(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private = root / "private.pem"
            public = root / "public.pem"
            manifest = root / "release.json"
            signature = root / "release.json.sig"

            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                check=True,
                capture_output=True,
            )
            der = subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-in",
                    str(public),
                    "-pubout",
                    "-outform",
                    "DER",
                ],
                check=True,
                capture_output=True,
            ).stdout
            payload = {
                "schema_version": 1,
                "component": "demo",
                "version": "v1.2.3",
                "revision": "abc123",
                "release_epoch": 42,
                "schema_digest": "a" * 64,
                "binary_sha256": "b" * 64,
                "signing_key_sha256": hashlib.sha256(der).hexdigest(),
                "signature_algorithm": "ed25519",
            }
            manifest.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-sign",
                    "-inkey",
                    str(private),
                    "-rawin",
                    "-in",
                    str(manifest),
                    "-out",
                    str(signature),
                ],
                check=True,
                capture_output=True,
            )

            result = verify_signed_manifest(
                manifest_path=manifest,
                signature_path=signature,
                public_key_path=public,
                expected_release="1.2.3",
                expected_revision="abc123",
                expected_component="demo",
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["release_epoch"], 42)

            payload["revision"] = "tampered"
            manifest.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(OpsPilotError, "signature verification failed"):
                verify_signed_manifest(
                    manifest_path=manifest,
                    signature_path=signature,
                    public_key_path=public,
                )


if __name__ == "__main__":
    unittest.main()
