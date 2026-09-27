from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .core import OpsPilotError, now


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost" or host in {"127.0.0.1", "::1"}:
        return True
    try:
        return socket.gethostbyname(host).startswith("127.")
    except (socket.gaierror, UnicodeError):
        return False


def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def json_pointer(payload: Any, pointer: str) -> Any:
    if pointer == "":
        return payload
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise OpsPilotError(f"invalid JSON pointer: {pointer!r}")
    current = payload
    for raw in pointer.split("/")[1:]:
        token = _decode_pointer_token(raw)
        if isinstance(current, dict):
            if token not in current:
                raise OpsPilotError(f"runtime health missing JSON pointer: {pointer}")
            current = current[token]
        elif isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise OpsPilotError(f"invalid list index in JSON pointer: {pointer}") from exc
            if index < 0 or index >= len(current):
                raise OpsPilotError(f"runtime health missing JSON pointer: {pointer}")
            current = current[index]
        else:
            raise OpsPilotError(f"runtime health missing JSON pointer: {pointer}")
    return current


def runtime_url(contract: dict[str, Any], override: str | None = None) -> str:
    base = override or contract.get("base_url")
    if not isinstance(base, str) or not base.strip():
        raise OpsPilotError("runtime contract base_url is required")
    base = base.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OpsPilotError(f"invalid runtime base_url: {base}")
    if parsed.scheme != "https" and not (
        contract.get("allow_http") is True and _is_loopback(parsed.hostname)
    ):
        raise OpsPilotError(f"refusing insecure non-loopback runtime URL: {base}")
    path = contract.get("health_path", "/healthz")
    if not isinstance(path, str) or not path.startswith("/"):
        raise OpsPilotError("runtime contract health_path must start with /")
    return f"{base}{path}"


def fetch_health(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OpsPilot/0.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise OpsPilotError(f"runtime health returned HTTP {response.status}")
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise OpsPilotError(f"runtime health returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpsPilotError(f"runtime health request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OpsPilotError("runtime health request timed out") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpsPilotError("runtime health did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpsPilotError("runtime health JSON must be an object")
    return payload


def verify_runtime(
    *,
    environment: str,
    contract: dict[str, Any],
    expected_revision: str | None = None,
    base_url: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    url = runtime_url(contract, base_url)
    payload = fetch_health(url, timeout)

    revision_pointer = contract.get("revision_pointer")
    revision = None
    if revision_pointer is not None:
        if not isinstance(revision_pointer, str):
            raise OpsPilotError("runtime revision_pointer must be a string")
        revision = json_pointer(payload, revision_pointer)
        if not isinstance(revision, str) or not revision:
            raise OpsPilotError("runtime revision value must be a non-empty string")
    if expected_revision and revision != expected_revision:
        raise OpsPilotError(
            f"runtime revision mismatch: expected {expected_revision!r}, got {revision!r}"
        )

    checks_cfg = contract.get("checks", [])
    if not isinstance(checks_cfg, list):
        raise OpsPilotError("runtime contract checks must be an array")
    checks: dict[str, bool] = {}
    values: dict[str, Any] = {}
    for item in checks_cfg:
        if not isinstance(item, dict):
            raise OpsPilotError("runtime check must be an object")
        name = item.get("name")
        pointer = item.get("pointer")
        if not isinstance(name, str) or not name:
            raise OpsPilotError("runtime check name is required")
        if not isinstance(pointer, str):
            raise OpsPilotError(f"runtime check {name} pointer is required")
        actual = json_pointer(payload, pointer)
        expected = item.get("equals", True)
        passed = actual == expected
        checks[name] = passed
        values[name] = actual
        if not passed:
            raise OpsPilotError(
                f"runtime check {name!r} failed: expected {expected!r}, got {actual!r}"
            )

    evidence: dict[str, Any] = {
        "verified": True,
        "at": now(),
        "environment": environment,
        "url": url,
        "revision": revision,
        "checks": checks,
        "values": values,
    }
    schema_pointer = contract.get("schema_digest_pointer")
    if schema_pointer is not None:
        if not isinstance(schema_pointer, str):
            raise OpsPilotError("runtime schema_digest_pointer must be a string")
        evidence["schema_digest"] = json_pointer(payload, schema_pointer)
    return evidence
