from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str, expect: int = 0):
        proc = subprocess.run(
            [sys.executable, "-m", "opspilot", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            expect,
            msg=f"stdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return proc

    def test_run_next_records_adapter_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            project = root / "project.json"
            project.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "demo"},
                        "adapters": {
                            "validate": {
                                "environment": "ci",
                                "command": ["python3", "-c", "raise SystemExit(7)"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.run_cli(
                "init",
                "--state-file",
                str(state),
                "--project-id",
                "demo",
                "--release",
                "v1",
            )
            self.run_cli(
                "run-next",
                "--state-file",
                str(state),
                "--project-file",
                str(project),
                expect=7,
            )
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "FAILED")
            self.assertEqual(saved["failed_action"], "validate")

    def test_dry_run_has_no_state_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            project = root / "project.json"
            project.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "demo"},
                        "adapters": {
                            "validate": {
                                "environment": "ci",
                                "command": ["false"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.run_cli(
                "init",
                "--state-file",
                str(state),
                "--project-id",
                "demo",
                "--release",
                "v1",
            )
            before = state.read_text(encoding="utf-8")
            self.run_cli(
                "run-next",
                "--state-file",
                str(state),
                "--project-file",
                str(project),
                "--dry-run",
            )
            self.assertEqual(before, state.read_text(encoding="utf-8"))

    def test_production_confirmation_precedes_adapter_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            project = root / "project.json"
            marker = root / "executed.txt"
            project.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "demo"},
                        "adapters": {
                            "deploy-canary": {
                                "environment": "production",
                                "command": [
                                    sys.executable,
                                    "-c",
                                    f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.run_cli(
                "init",
                "--state-file",
                str(state),
                "--project-id",
                "demo",
                "--release",
                "v2",
                "--last-known-good",
                "v1",
            )
            saved = json.loads(state.read_text(encoding="utf-8"))
            saved["state"] = "CANDIDATE_READY"
            state.write_text(json.dumps(saved), encoding="utf-8")

            self.run_cli(
                "run-next",
                "--state-file",
                str(state),
                "--project-file",
                str(project),
                expect=2,
            )
            self.assertFalse(marker.exists(), "production adapter ran before confirmation")

            self.run_cli(
                "run-next",
                "--state-file",
                str(state),
                "--project-file",
                str(project),
                "--confirm",
                "canary:v2",
            )
            self.assertTrue(marker.exists())

    def test_candidate_policy_precedes_adapter_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            project = root / "project.json"
            marker = root / "candidate.txt"
            project.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": {"id": "demo"},
                        "policy": {"candidate": {"require_signed_release": True}},
                        "adapters": {
                            "candidate": {
                                "environment": "release",
                                "command": [
                                    sys.executable,
                                    "-c",
                                    f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.run_cli(
                "init",
                "--state-file",
                str(state),
                "--project-id",
                "demo",
                "--release",
                "v3",
            )
            saved = json.loads(state.read_text(encoding="utf-8"))
            saved["state"] = "STAGING_QUALIFIED"
            state.write_text(json.dumps(saved), encoding="utf-8")

            self.run_cli(
                "run-next",
                "--state-file",
                str(state),
                "--project-file",
                str(project),
                expect=2,
            )
            self.assertFalse(marker.exists(), "candidate adapter ran before policy gate")


if __name__ == "__main__":
    unittest.main()
