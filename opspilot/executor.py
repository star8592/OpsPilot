from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any

from .core import ACTION_ENVIRONMENT, OpsPilotError


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def run_adapter(
    *,
    action: str,
    adapter: dict[str, Any],
    project_id: str,
    release: str,
    revision: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    required_environment = ACTION_ENVIRONMENT[action]
    if adapter.get("environment") != required_environment:
        raise OpsPilotError(f"adapter environment mismatch for {action}")
    argv = adapter["command"]
    if dry_run:
        return {
            "dry_run": True,
            "action": action,
            "environment": required_environment,
            "command": argv,
        }

    env = os.environ.copy()
    env.update(
        {
            "OPSPILOT_PROJECT_ID": project_id,
            "OPSPILOT_RELEASE": release,
            "OPSPILOT_REVISION": revision or "",
            "OPSPILOT_ACTION": action,
            "OPSPILOT_ENVIRONMENT": required_environment,
        }
    )
    proc = subprocess.run(
        argv,
        cwd=adapter.get("cwd"),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "dry_run": False,
        "action": action,
        "environment": required_environment,
        "exit_code": proc.returncode,
        "stdout_sha256": _digest(proc.stdout),
        "stderr_sha256": _digest(proc.stderr),
        "stdout_bytes": len(proc.stdout.encode("utf-8", errors="replace")),
        "stderr_bytes": len(proc.stderr.encode("utf-8", errors="replace")),
    }
