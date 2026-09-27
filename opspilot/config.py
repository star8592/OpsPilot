from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import ACTION_ENVIRONMENT, OpsPilotError, SCHEMA_VERSION, read_json


def load_project(path: Path) -> dict[str, Any]:
    cfg = read_json(path)
    if cfg.get("schema_version") != SCHEMA_VERSION:
        raise OpsPilotError("unsupported project config schema_version")

    project = cfg.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("id"), str) or not project["id"]:
        raise OpsPilotError("project.id is required")

    release = cfg.get("release", {})
    if not isinstance(release, dict):
        raise OpsPilotError("release must be an object")
    component = release.get("component")
    if component is not None and (not isinstance(component, str) or not component):
        raise OpsPilotError("release.component must be a non-empty string")

    environments = cfg.get("environments", {})
    if not isinstance(environments, dict):
        raise OpsPilotError("environments must be an object")
    for name, env in environments.items():
        if not isinstance(name, str) or not name:
            raise OpsPilotError("environment names must be non-empty strings")
        if not isinstance(env, dict):
            raise OpsPilotError(f"environment {name} must be an object")
        runtime = env.get("runtime")
        if runtime is not None and not isinstance(runtime, dict):
            raise OpsPilotError(f"environment {name}.runtime must be an object")
        if isinstance(runtime, dict):
            checks = runtime.get("checks", [])
            if not isinstance(checks, list):
                raise OpsPilotError(f"environment {name}.runtime.checks must be an array")
            seen: set[str] = set()
            for check in checks:
                if not isinstance(check, dict):
                    raise OpsPilotError(f"environment {name}.runtime check must be an object")
                check_name = check.get("name")
                pointer = check.get("pointer")
                if not isinstance(check_name, str) or not check_name:
                    raise OpsPilotError(f"environment {name}.runtime check name is required")
                if check_name in seen:
                    raise OpsPilotError(f"environment {name}.runtime duplicate check: {check_name}")
                seen.add(check_name)
                if not isinstance(pointer, str) or not pointer.startswith("/"):
                    raise OpsPilotError(f"environment {name}.runtime check {check_name} pointer is invalid")

    policy = cfg.get("policy", {})
    if not isinstance(policy, dict):
        raise OpsPilotError("policy must be an object")
    candidate = policy.get("candidate", {})
    if not isinstance(candidate, dict):
        raise OpsPilotError("policy.candidate must be an object")
    runtime_env = candidate.get("require_runtime_verification")
    if runtime_env is not None and (not isinstance(runtime_env, str) or not runtime_env):
        raise OpsPilotError("policy.candidate.require_runtime_verification must be a non-empty string")
    if runtime_env is not None and runtime_env not in environments:
        raise OpsPilotError("policy.candidate runtime environment is not declared")
    require_signed = candidate.get("require_signed_release")
    if require_signed is not None and not isinstance(require_signed, bool):
        raise OpsPilotError("policy.candidate.require_signed_release must be boolean")
    required_checks = candidate.get("required_runtime_checks", [])
    if not isinstance(required_checks, list) or not all(isinstance(v, str) and v for v in required_checks):
        raise OpsPilotError("policy.candidate.required_runtime_checks must be a string array")
    if runtime_env is None and required_checks:
        raise OpsPilotError("candidate required_runtime_checks needs require_runtime_verification")
    if runtime_env is not None:
        runtime = environments[runtime_env].get("runtime")
        if not isinstance(runtime, dict):
            raise OpsPilotError("candidate runtime environment has no runtime contract")
        declared = {check.get("name") for check in runtime.get("checks", []) if isinstance(check, dict)}
        missing = [name for name in required_checks if name not in declared]
        if missing:
            raise OpsPilotError("candidate required runtime checks are undeclared: " + ", ".join(missing))

    adapters = cfg.get("adapters", {})
    if not isinstance(adapters, dict):
        raise OpsPilotError("adapters must be an object")
    for action, adapter in adapters.items():
        if action not in ACTION_ENVIRONMENT:
            raise OpsPilotError(f"unknown adapter action: {action}")
        if not isinstance(adapter, dict):
            raise OpsPilotError(f"adapter {action} must be an object")
        required_environment = ACTION_ENVIRONMENT[action]
        if adapter.get("environment") != required_environment:
            raise OpsPilotError(
                f"adapter {action} must declare environment={required_environment!r}"
            )
        command = adapter.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
            raise OpsPilotError(f"adapter {action}.command must be a non-empty string array")
        cwd = adapter.get("cwd")
        if cwd is not None and (not isinstance(cwd, str) or not cwd):
            raise OpsPilotError(f"adapter {action}.cwd must be a non-empty string")

    return cfg
