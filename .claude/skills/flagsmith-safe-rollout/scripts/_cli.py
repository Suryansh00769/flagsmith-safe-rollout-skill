"""Shared Flagsmith CLI v2 wrapper and token-compact JSON utilities."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CliResult:
    """Normalized result from invoking the Flagsmith CLI."""

    ok: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    error_kind: str | None = None


def find_flagsmith_bin() -> str | None:
    """Locate the Flagsmith CLI binary in PATH or standard user bin directories."""
    found = shutil.which("flagsmith")
    if found:
        return found

    candidates = [
        Path.home() / ".local" / "bin" / "flagsmith.exe",
        Path.home() / ".local" / "bin" / "flagsmith",
        Path("/usr/local/bin/flagsmith"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def load_flagsmith_config(project_root: Path) -> dict[str, Any] | None:
    """Read flagsmith.json from project_root if present and valid."""
    cfg_path = project_root / "flagsmith.json"
    if not cfg_path.is_file():
        return None
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _classify_error(stderr: str) -> str:
    lower = stderr.lower()
    if "keychain" in lower or "flagsmith_api_key" in lower or "not logged in" in lower:
        return "auth_unavailable"
    if "no such host" in lower or "timeout" in lower or "connection" in lower:
        return "network_error"
    return "cli_error"


def run_flagsmith(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 20,
    no_input: bool = True,
) -> CliResult:
    """Run flagsmith CLI with --no-input safety and normalized error reporting."""
    binary = find_flagsmith_bin()
    if not binary:
        return CliResult(
            ok=False,
            returncode=127,
            stdout="",
            stderr="flagsmith CLI binary not found in PATH or ~/.local/bin.",
            command=["flagsmith", *args],
            error_kind="binary_missing",
        )

    cmd = [binary, *args]
    if no_input and "--no-input" not in cmd:
        cmd.append("--no-input")

    env = os.environ.copy()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode == 0:
        return CliResult(
            ok=True,
            returncode=0,
            stdout=stdout,
            stderr=stderr,
            command=cmd,
        )
    return CliResult(
        ok=False,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        command=cmd,
        error_kind=_classify_error(stderr),
    )


def run_flagsmith_json(
    args: list[str],
    *,
    jq_expr: str | None = None,
    cwd: Path | None = None,
) -> tuple[Any | None, CliResult]:
    """Run a Flagsmith CLI command with --json / --jq and parse the JSON result."""
    cli_args = list(args)
    if jq_expr:
        cli_args.extend(["--jq", jq_expr])
    elif "--json" not in cli_args:
        cli_args.append("--json")

    res = run_flagsmith(cli_args, cwd=cwd)
    if not res.ok:
        return None, res

    if not res.stdout:
        return None, res
    try:
        return json.loads(res.stdout), res
    except json.JSONDecodeError as exc:
        return None, CliResult(
            ok=False,
            returncode=res.returncode,
            stdout=res.stdout,
            stderr=f"Invalid JSON from flagsmith CLI: {exc}",
            command=res.command,
            error_kind="invalid_json",
        )


def format_command(cmd: list[str]) -> str:
    """Format a Flagsmith CLI command safely for human preview and copy-paste."""
    parts = ["flagsmith"]
    for token in cmd:
        if any(ch in token for ch in (' ', '"', '{', '[', '*')):
            escaped = token.replace('"', '\\"')
            parts.append(f'"{escaped}"')
        else:
            parts.append(token)
    return " ".join(parts)


def emit_json(payload: dict[str, Any]) -> None:
    """Print compact single-line JSON to minimize agent context tokens."""
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
