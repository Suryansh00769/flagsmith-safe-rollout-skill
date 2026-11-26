"""Phase 2: Scan codebase & git diff for unflagged changes, missing fallbacks, and Flagsmith drift."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from _cli import emit_json, run_flagsmith_json

FLAG_METHODS = {"has_feature", "get_feature_value", "is_feature_enabled", "evaluate"}
DEFAULT_EXCLUDES = {".venv", "venv", ".git", "__pycache__", "node_modules", "tests"}
JQ_FLAG_SUMMARY = "[.[] | {name: .feature.name, enabled: .enabled, value: .feature_state_value}]"


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def scan_python_flag_calls(root: Path) -> list[dict[str, Any]]:
    """Find Flagsmith flag evaluations in Python source and check for explicit fallbacks."""
    findings: list[dict[str, Any]] = []
    for py_file in _iter_python_files(root):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        client_has_default = "default_flag_handler" in source
        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in FLAG_METHODS:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue

            flag_name = node.args[0].value
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            line_text = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
            has_explicit_fallback = bool(
                client_has_default
                or "default" in kw_names
                or "default_enabled" in kw_names
                or "default_value" in kw_names
                or "fallback" in kw_names
                or len(node.args) >= 2
                or "default=" in line_text
            )
            findings.append(
                {
                    "flag": flag_name,
                    "method": node.func.attr,
                    "file": str(py_file.relative_to(root)).replace("\\", "/"),
                    "line": node.lineno,
                    "has_safe_fallback": has_explicit_fallback,
                }
            )
    return findings


def scan_diff_for_unflagged_symbols(root: Path, diff_base: str | None = None, diff_file: Path | None = None) -> list[dict[str, Any]]:
    """Inspect a git diff (or patch file) for newly added Python functions lacking flag checks."""
    if diff_file is not None:
        diff_text = diff_file.read_text(encoding="utf-8")
    elif diff_base:
        proc = subprocess.run(
            ["git", "diff", diff_base, "--", "*.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        diff_text = proc.stdout if proc.returncode == 0 else ""
    else:
        return []

    suggestions: list[dict[str, Any]] = []
    current_file: str | None = None
    added_lines: list[str] = []

    def _flush() -> None:
        if not current_file or not added_lines:
            return
        chunk = "\n".join(added_lines)
        if any(method in chunk for method in FLAG_METHODS) or "flag_client" in chunk:
            return
        for match in re.finditer(r"^\+\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", chunk, re.MULTILINE):
            fn_name = match.group(1)
            if fn_name.startswith("_"):
                continue
            suggestions.append(
                {
                    "file": current_file,
                    "symbol": fn_name,
                    "suggested_flag": f"enable_{fn_name}"[:50],
                }
            )

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            _flush()
            current_file = line[6:].strip()
            added_lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line)
    _flush()
    return suggestions


def load_live_flags(root: Path, offline_flags_path: Path | None = None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Load minimal flag metadata via Flagsmith CLI --jq or an offline JSON fixture."""
    if offline_flags_path is not None:
        raw = json.loads(offline_flags_path.read_text(encoding="utf-8"))
        items = raw.get("feature_states", raw) if isinstance(raw, dict) else raw
        mapped: dict[str, dict[str, Any]] = {}
        for item in items:
            name = item.get("name") or item.get("feature", {}).get("name")
            if name:
                mapped[name] = {
                    "name": name,
                    "enabled": bool(item.get("enabled", False)),
                    "value": item.get("value", item.get("feature_state_value")),
                }
        return mapped, None

    data, res = run_flagsmith_json(["flag", "list"], jq_expr=JQ_FLAG_SUMMARY, cwd=root)
    if not res.ok or not isinstance(data, list):
        return {}, res.stderr
    return {item["name"]: item for item in data if isinstance(item, dict) and "name" in item}, None


def run_scan(
    root: Path,
    *,
    diff_base: str | None = None,
    diff_file: Path | None = None,
    offline_flags: Path | None = None,
) -> dict[str, Any]:
    """Cross-reference codebase flag usage, diff changes, and Flagsmith states."""
    code_calls = scan_python_flag_calls(root)
    diff_suggestions = scan_diff_for_unflagged_symbols(root, diff_base=diff_base, diff_file=diff_file)
    live_flags, flag_error = load_live_flags(root, offline_flags_path=offline_flags)

    code_flag_names = {item["flag"] for item in code_calls}
    missing_fallback = [item for item in code_calls if not item["has_safe_fallback"]]
    missing_in_flagsmith = sorted(code_flag_names - set(live_flags)) if live_flags else []
    unused_in_code = sorted(set(live_flags) - code_flag_names) if live_flags else []

    return {
        "phase": "scan",
        "code_flag_count": len(code_calls),
        "unique_code_flags": sorted(code_flag_names),
        "live_flag_count": len(live_flags) if live_flags else None,
        "flag_fetch_warning": flag_error,
        "missing_fallback_in_code": missing_fallback,
        "missing_in_flagsmith": missing_in_flagsmith,
        "unused_in_code": unused_in_code,
        "unflagged_diff_symbols": diff_suggestions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit codebase flags and git diffs against Flagsmith")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--diff-base", type=str, default=None, help="Git ref to diff against (e.g. HEAD)")
    parser.add_argument("--diff-file", type=Path, default=None, help="Patch file to scan instead of git diff")
    parser.add_argument("--offline-flags", type=Path, default=None, help="Offline flag list or env document JSON")
    args = parser.parse_args()

    result = run_scan(
        args.project_root.resolve(),
        diff_base=args.diff_base,
        diff_file=args.diff_file,
        offline_flags=args.offline_flags,
    )
    emit_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
