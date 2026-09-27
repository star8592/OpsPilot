from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .core import OpsPilotError, now


def _openssl(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["openssl", *args], capture_output=True, check=False, timeout=10)
    except FileNotFoundError as exc:
        raise OpsPilotError("openssl is required for Ed25519 verification") from exc
    except subprocess.TimeoutExpired as exc:
        raise OpsPilotError("openssl verification timed out") from exc


def public_key_sha256(public_key: Path) -> str:
    proc = _openssl(["pkey", "-pubin", "-in", str(public_key), "-pubout", "-outform", "DER"])
    if proc.returncode != 0:
        raise OpsPilotError("failed to parse release public key")
    return hashlib.sha256(proc.stdout).hexdigest()


def _validate_hex_digest(name: str, value: Any, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise OpsPilotError(f"release manifest {name} is invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise OpsPilotError(f"release manifest {name} is invalid") from exc
    return value


def verify_signed_manifest(
    *,
    manifest_path: Path,
    signature_path: Path,
    public_key_path: Path,
    expected_release: str | None = None,
    expected_revision: str | None = None,
    expected_component: str | None = None,
) -> dict[str, Any]:
    for path in (manifest_path, signature_path, public_key_path):
        if not path.is_file():
            raise OpsPilotError(f"release verification file missing: {path}")

    proc = _openssl(
        [
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_key_path),
            "-rawin",
            "-in",
            str(manifest_path),
            "-sigfile",
            str(signature_path),
        ]
    )
    if proc.returncode != 0:
        raise OpsPilotError("release manifest signature verification failed")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OpsPilotError("release manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise OpsPilotError("unsupported release manifest schema")
    if manifest.get("signature_algorithm") != "ed25519":
        raise OpsPilotError("release manifest must use ed25519")

    component = manifest.get("component")
    version = manifest.get("version")
    revision = manifest.get("revision")
    epoch = manifest.get("release_epoch")
    if not isinstance(component, str) or not component:
        raise OpsPilotError("release manifest component is missing")
    if expected_component and component != expected_component:
        raise OpsPilotError("release manifest component does not match expected component")
    if not isinstance(version, str) or not version:
        raise OpsPilotError("release manifest version is missing")
    if not isinstance(revision, str) or not revision:
        raise OpsPilotError("release manifest revision is missing")
    if not isinstance(epoch, int) or epoch < 1:
        raise OpsPilotError("release manifest release_epoch is invalid")

    if expected_release and version.lstrip("v") != expected_release.lstrip("v"):
        raise OpsPilotError("release manifest version does not match expected release")
    if expected_revision and revision != expected_revision:
        raise OpsPilotError("release manifest revision does not match expected revision")

    actual_key_digest = public_key_sha256(public_key_path)
    declared_key_digest = _validate_hex_digest(
        "signing_key_sha256", manifest.get("signing_key_sha256"), required=True
    )
    if declared_key_digest != actual_key_digest:
        raise OpsPilotError("release manifest signing key digest mismatch")
    schema_digest = _validate_hex_digest(
        "schema_digest", manifest.get("schema_digest"), required=False
    )
    binary_digest = _validate_hex_digest(
        "binary_sha256", manifest.get("binary_sha256"), required=False
    )

    return {
        "verified": True,
        "at": now(),
        "component": component,
        "version": version,
        "revision": revision,
        "release_epoch": epoch,
        "schema_digest": schema_digest,
        "binary_sha256": binary_digest,
        "signing_key_sha256": actual_key_digest,
        "signature_algorithm": "ed25519",
    }
