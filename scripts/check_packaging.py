#!/usr/bin/env python3
"""Cheap packaging-configuration validation (runs anywhere, incl. CI).

Verifies the installer inputs are coherent without needing Rust/Windows:
Tauri config parses, bundle is enabled for NSIS, icons/resources/external
binary declarations point at real paths (or documented build outputs),
NSIS hooks exist, and versions agree across Python/Tauri/npm.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    errors: list[str] = []
    tauri = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())
    bundle = tauri.get("bundle", {})
    if bundle.get("active") is not True:
        errors.append("tauri bundle.active must be true for installer builds")
    if "nsis" not in bundle.get("targets", []):
        errors.append("tauri bundle targets must include 'nsis'")
    for icon in bundle.get("icon", []):
        if not (ROOT / "src-tauri" / icon).is_file():
            errors.append(f"missing bundle icon: {icon}")
    for resource in bundle.get("resources", []):
        if not (ROOT / "src-tauri" / resource).is_file():
            errors.append(f"missing bundle resource: {resource}")
    nsis = bundle.get("windows", {}).get("nsis", {})
    if nsis.get("installMode") != "currentUser":
        errors.append("NSIS installMode should be currentUser (no admin)")
    hooks = nsis.get("installerHooks")
    if hooks and not (ROOT / "src-tauri" / hooks).is_file():
        errors.append(f"missing NSIS installer hooks: {hooks}")
    for external in bundle.get("externalBin", []):
        readme = ROOT / "src-tauri" / "binaries" / "README.md"
        if not readme.is_file():
            errors.append(f"externalBin {external} declared but binaries/README.md missing")

    def version_of(pattern: str, path: Path) -> str | None:
        match = re.search(pattern, path.read_text(), re.M)
        return match.group(1) if match else None

    versions = {
        "tauri.conf.json": tauri.get("version"),
        "package.json": json.loads((ROOT / "package.json").read_text()).get("version"),
        "pyproject.toml": version_of(r'^version = "([^"]+)"', ROOT / "pyproject.toml"),
        "Cargo.toml": version_of(r'^version = "([^"]+)"', ROOT / "src-tauri/Cargo.toml"),
    }
    if len(set(versions.values())) != 1:
        errors.append(f"version mismatch across packaging files: {versions}")

    if errors:
        for error in errors:
            print(f"packaging check: {error}", file=sys.stderr)
        return 1
    print(f"packaging config OK (version {versions['tauri.conf.json']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
