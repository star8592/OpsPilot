from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_project
from .core import (
    ACTION_ENVIRONMENT,
    OpsPilotError,
    atomic_write,
    fail,
    new_state,
    next_action,
    read_json,
    require_confirmation,
    rollback,
    transition,
    validate_state,
)
from .executor import run_adapter
from .release import verify_signed_manifest
from .runtime import verify_runtime

DEFAULT_STATE = ".opspilot/state.json"


def state_path(args: argparse.Namespace) -> Path:
    return Path(args.state_file)


def load_state(args: argparse.Namespace) -> dict:
    state = read_json(state_path(args))
    validate_state(state)
    return state


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def evidence_from_text(text: str | None) -> dict:
    return {"note": text} if text else {}


def _candidate_policy(state: dict, cfg: dict) -> None:
    policy = cfg.get("policy", {}).get("candidate", {})
    runtime_env = policy.get("require_runtime_verification")
    if runtime_env:
        evidence = state.get("verifications", {}).get("runtime", {}).get(runtime_env)
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise OpsPilotError(f"candidate requires verified runtime environment {runtime_env!r}")
        if state.get("revision") and evidence.get("revision") != state.get("revision"):
            raise OpsPilotError("candidate runtime revision does not match release revision")
        required_checks = policy.get("required_runtime_checks", [])
        checks = evidence.get("checks", {})
        missing = [name for name in required_checks if checks.get(name) is not True]
        if missing:
            raise OpsPilotError("candidate runtime checks not satisfied: " + ", ".join(missing))

    if policy.get("require_signed_release") is True:
        evidence = state.get("verifications", {}).get("release_manifest")
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            raise OpsPilotError("candidate requires verified signed release manifest")
        if state.get("revision") and evidence.get("revision") != state.get("revision"):
            raise OpsPilotError("candidate release manifest revision does not match release revision")
        expected_component = cfg.get("release", {}).get("component")
        if expected_component and evidence.get("component") != expected_component:
            raise OpsPilotError("candidate release manifest component does not match project")
        release = str(state.get("release", "")).lstrip("v")
        version = str(evidence.get("version", "")).lstrip("v")
        if release != version:
            raise OpsPilotError("candidate release manifest version does not match release")
        if runtime_env:
            runtime = state.get("verifications", {}).get("runtime", {}).get(runtime_env, {})
            runtime_schema = runtime.get("schema_digest")
            release_schema = evidence.get("schema_digest")
            if runtime_schema is not None and release_schema != runtime_schema:
                raise OpsPilotError("candidate release manifest schema digest does not match runtime")


def cmd_init(args: argparse.Namespace) -> int:
    path = state_path(args)
    if path.exists() and not args.force:
        raise OpsPilotError(f"state already exists: {path}")
    state = new_state(
        project_id=args.project_id,
        release=args.release,
        revision=args.revision,
        last_known_good=args.last_known_good,
        environment=args.environment,
    )
    atomic_write(path, state)
    print_json(state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = load_state(args)
    print_json(
        {
            "project_id": state["project_id"],
            "release": state["release"],
            "environment": state["environment"],
            "revision": state.get("revision"),
            "state": state["state"],
            "next_action": next_action(state),
            "last_known_good": state.get("last_known_good"),
            "failed_action": state.get("failed_action"),
            "rollback_release": state.get("rollback_release"),
            "updated_at": state["updated_at"],
        }
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    state = load_state(args)
    action = next_action(state)
    print_json(
        {
            "project_id": state["project_id"],
            "release": state["release"],
            "state": state["state"],
            "next_action": action,
            "environment": ACTION_ENVIRONMENT.get(action) if action else None,
        }
    )
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    state = load_state(args)
    if args.action == "candidate":
        if not args.project_file:
            raise OpsPilotError("candidate requires --project-file so policy cannot be bypassed")
        _candidate_policy(state, load_project(Path(args.project_file)))
    transition(
        state,
        args.action,
        evidence=evidence_from_text(args.evidence),
        confirmation=args.confirm,
    )
    atomic_write(state_path(args), state)
    print_json(state)
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    state = load_state(args)
    fail(state, args.action, evidence_from_text(args.evidence))
    atomic_write(state_path(args), state)
    print_json(state)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    state = load_state(args)
    rollback(state, confirmation=args.confirm, evidence=evidence_from_text(args.evidence))
    atomic_write(state_path(args), state)
    print_json(state)
    return 0


def cmd_validate_project(args: argparse.Namespace) -> int:
    cfg = load_project(Path(args.project_file))
    print_json(
        {
            "status": "pass",
            "project_id": cfg["project"]["id"],
            "adapters": sorted(cfg.get("adapters", {})),
        }
    )
    return 0


def cmd_verify_runtime(args: argparse.Namespace) -> int:
    state = load_state(args)
    cfg = load_project(Path(args.project_file))
    env = cfg.get("environments", {}).get(args.environment)
    if not isinstance(env, dict) or not isinstance(env.get("runtime"), dict):
        raise OpsPilotError(f"no runtime contract configured for environment {args.environment!r}")
    result = verify_runtime(
        environment=args.environment,
        contract=env["runtime"],
        expected_revision=args.expected_revision or state.get("revision"),
        base_url=args.base_url,
        timeout=args.timeout,
    )
    if args.record:
        state.setdefault("verifications", {}).setdefault("runtime", {})[args.environment] = result
        state.setdefault("history", []).append(
            {
                "at": result["at"],
                "action": "verify-runtime",
                "state": state["state"],
                "details": {"environment": args.environment, "checks": result["checks"]},
            }
        )
        state["updated_at"] = result["at"]
        atomic_write(state_path(args), state)
    print_json(result)
    return 0


def cmd_verify_release(args: argparse.Namespace) -> int:
    state = load_state(args)
    cfg = load_project(Path(args.project_file)) if args.project_file else {}
    expected_component = cfg.get("release", {}).get("component") if cfg else None
    result = verify_signed_manifest(
        manifest_path=Path(args.manifest),
        signature_path=Path(args.signature),
        public_key_path=Path(args.public_key),
        expected_release=state.get("release"),
        expected_revision=state.get("revision"),
        expected_component=expected_component,
    )
    if args.record:
        state.setdefault("verifications", {})["release_manifest"] = result
        state.setdefault("history", []).append(
            {
                "at": result["at"],
                "action": "verify-release",
                "state": state["state"],
                "details": {"version": result["version"], "revision": result["revision"]},
            }
        )
        state["updated_at"] = result["at"]
        atomic_write(state_path(args), state)
    print_json(result)
    return 0


def cmd_run_next(args: argparse.Namespace) -> int:
    state = load_state(args)
    action = next_action(state)
    if not action:
        raise OpsPilotError(f"no next action from {state['state']}")
    cfg = load_project(Path(args.project_file))
    if cfg["project"]["id"] != state["project_id"]:
        raise OpsPilotError("project config id does not match state project_id")

    adapter = cfg.get("adapters", {}).get(action)

    # All policy and confirmation gates execute before any adapter process.
    if action == "candidate":
        _candidate_policy(state, cfg)
    require_confirmation(action, state, args.confirm)

    # Candidate is allowed to be a Core-only policy gate.
    if adapter is None and action == "candidate":
        result = {
            "policy_only": True,
            "action": action,
            "environment": ACTION_ENVIRONMENT[action],
        }
        if args.dry_run:
            print_json(result)
            return 0
        transition(state, action, evidence=result, confirmation=args.confirm)
        atomic_write(state_path(args), state)
        print_json(result)
        return 0

    if not isinstance(adapter, dict):
        raise OpsPilotError(f"no adapter configured for action {action}")

    result = run_adapter(
        action=action,
        adapter=adapter,
        project_id=state["project_id"],
        release=state["release"],
        revision=state.get("revision"),
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print_json(result)
        return 0
    if result["exit_code"] != 0:
        fail(state, action, result)
        atomic_write(state_path(args), state)
        print_json(result)
        return int(result["exit_code"]) or 1

    transition(state, action, evidence=result, confirmation=args.confirm)
    atomic_write(state_path(args), state)
    print_json(result)
    return 0


def add_state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-file", default=DEFAULT_STATE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opspilot",
        description="Policy-driven production delivery control plane",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    add_state(p)
    p.add_argument("--project-id", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--revision")
    p.add_argument("--last-known-good")
    p.add_argument("--environment", default="production")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    for name, func in (("status", cmd_status), ("plan", cmd_plan)):
        p = sub.add_parser(name)
        add_state(p)
        p.set_defaults(func=func)

    p = sub.add_parser("advance")
    add_state(p)
    p.add_argument("action", choices=sorted(k for k in ACTION_ENVIRONMENT if k != "rollback"))
    p.add_argument("--evidence")
    p.add_argument("--confirm")
    p.add_argument("--project-file")
    p.set_defaults(func=cmd_advance)

    p = sub.add_parser("fail")
    add_state(p)
    p.add_argument("action")
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_fail)

    p = sub.add_parser("rollback")
    add_state(p)
    p.add_argument("--confirm", required=True)
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("validate-project")
    p.add_argument("--project-file", required=True)
    p.set_defaults(func=cmd_validate_project)

    p = sub.add_parser("verify-runtime")
    add_state(p)
    p.add_argument("--project-file", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--base-url")
    p.add_argument("--expected-revision")
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--record", action="store_true")
    p.set_defaults(func=cmd_verify_runtime)

    p = sub.add_parser("verify-release")
    add_state(p)
    p.add_argument("--manifest", required=True)
    p.add_argument("--signature", required=True)
    p.add_argument("--public-key", required=True)
    p.add_argument("--project-file")
    p.add_argument("--record", action="store_true")
    p.set_defaults(func=cmd_verify_release)

    p = sub.add_parser("run-next")
    add_state(p)
    p.add_argument("--project-file", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm")
    p.set_defaults(func=cmd_run_next)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except OpsPilotError as exc:
        print(f"OPSPILOT_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
