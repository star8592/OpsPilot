from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

FORWARD_STATES = [
    "PLANNED",
    "VALIDATED",
    "STAGING_DEPLOYED",
    "STAGING_QUALIFIED",
    "CANDIDATE_READY",
    "CANARY_DEPLOYED",
    "CANARY_HEALTHY",
    "PRODUCTION_ACTIVE",
    "STABLE",
]

TERMINAL_STATES = {"FAILED", "ROLLED_BACK"}

ACTION_TRANSITIONS = {
    "validate": ("PLANNED", "VALIDATED"),
    "deploy-staging": ("VALIDATED", "STAGING_DEPLOYED"),
    "smoke": ("STAGING_DEPLOYED", "STAGING_QUALIFIED"),
    "candidate": ("STAGING_QUALIFIED", "CANDIDATE_READY"),
    "deploy-canary": ("CANDIDATE_READY", "CANARY_DEPLOYED"),
    "canary-health": ("CANARY_DEPLOYED", "CANARY_HEALTHY"),
    "promote": ("CANARY_HEALTHY", "PRODUCTION_ACTIVE"),
    "stabilize": ("PRODUCTION_ACTIVE", "STABLE"),
}

ACTION_ENVIRONMENT = {
    "validate": "ci",
    "deploy-staging": "staging",
    "smoke": "staging",
    "candidate": "release",
    "deploy-canary": "production",
    "canary-health": "production",
    "promote": "production",
    "stabilize": "production",
    "rollback": "production",
}

PRODUCTION_MUTATIONS = {"deploy-canary", "promote", "rollback"}


class OpsPilotError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpsPilotError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OpsPilotError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OpsPilotError(f"expected JSON object: {path}")
    return value


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def append_history(state: dict[str, Any], action: str, details: dict[str, Any] | None = None) -> None:
    event_time = now()
    state.setdefault("history", []).append(
        {
            "at": event_time,
            "action": action,
            "state": state["state"],
            "details": details or {},
        }
    )
    state["updated_at"] = event_time


def new_state(
    *,
    project_id: str,
    release: str,
    revision: str | None = None,
    last_known_good: str | None = None,
    environment: str = "production",
) -> dict[str, Any]:
    if not project_id.strip():
        raise OpsPilotError("project_id is required")
    if not release.strip():
        raise OpsPilotError("release is required")
    if not environment.strip():
        raise OpsPilotError("environment is required")
    created = now()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "environment": environment,
        "release": release,
        "revision": revision,
        "state": "PLANNED",
        "last_known_good": last_known_good,
        "failed_action": None,
        "rollback_release": None,
        "verifications": {},
        "history": [],
        "created_at": created,
        "updated_at": created,
    }
    append_history(state, "init", {"release": release, "revision": revision})
    return state


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise OpsPilotError("unsupported state schema_version")
    if not isinstance(state.get("project_id"), str) or not state["project_id"]:
        raise OpsPilotError("state project_id is missing")
    if not isinstance(state.get("environment"), str) or not state["environment"]:
        raise OpsPilotError("state environment is missing")
    if not isinstance(state.get("release"), str) or not state["release"]:
        raise OpsPilotError("state release is missing")
    current = state.get("state")
    if current not in set(FORWARD_STATES) | TERMINAL_STATES:
        raise OpsPilotError(f"invalid state: {current!r}")


def next_action(state: dict[str, Any]) -> str | None:
    validate_state(state)
    if state["state"] in TERMINAL_STATES or state["state"] == "STABLE":
        return None
    for action, (expected, _target) in ACTION_TRANSITIONS.items():
        if expected == state["state"]:
            return action
    return None


def expected_confirmation(action: str, state: dict[str, Any]) -> str | None:
    if action == "deploy-canary":
        return f"canary:{state['release']}"
    if action == "promote":
        return f"production:{state['release']}"
    if action == "rollback":
        target = state.get("last_known_good")
        return f"rollback:{target}" if target else None
    return None


def require_confirmation(action: str, state: dict[str, Any], confirmation: str | None) -> None:
    if action not in PRODUCTION_MUTATIONS:
        return
    expected = expected_confirmation(action, state)
    if expected is None:
        raise OpsPilotError(f"{action} requires last_known_good")
    if confirmation != expected:
        raise OpsPilotError(f"{action} requires --confirm {expected}")


def transition(
    state: dict[str, Any],
    action: str,
    *,
    evidence: dict[str, Any] | None = None,
    confirmation: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    if action not in ACTION_TRANSITIONS:
        raise OpsPilotError(f"unknown transition action: {action}")
    expected, target = ACTION_TRANSITIONS[action]
    if state["state"] != expected:
        raise OpsPilotError(f"{action} requires state {expected}; current state is {state['state']}")
    require_confirmation(action, state, confirmation)
    state["state"] = target
    state["failed_action"] = None
    append_history(
        state,
        action,
        {
            "environment": ACTION_ENVIRONMENT[action],
            "evidence": evidence or {},
        },
    )
    return state


def fail(state: dict[str, Any], action: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_state(state)
    if state["state"] in TERMINAL_STATES:
        raise OpsPilotError(f"cannot fail terminal state {state['state']}")
    previous = state["state"]
    state["state"] = "FAILED"
    state["failed_action"] = action
    append_history(
        state,
        "fail",
        {"failed_action": action, "from_state": previous, "evidence": evidence or {}},
    )
    return state


def rollback(
    state: dict[str, Any],
    *,
    confirmation: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_state(state)
    require_confirmation("rollback", state, confirmation)
    previous = state["state"]
    target = state["last_known_good"]
    state["state"] = "ROLLED_BACK"
    state["rollback_release"] = target
    append_history(
        state,
        "rollback",
        {
            "from_state": previous,
            "target": target,
            "environment": "production",
            "evidence": evidence or {},
        },
    )
    return state
