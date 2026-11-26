"""Phase 4: Identify stale/archived flags, locate dead branches, and archive safely."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _cli import emit_json, format_command, run_flagsmith, run_flagsmith_json
from scan_flags import scan_python_flag_calls

JQ_FEATURE_SUMMARY = "[.[] | {name: .name, is_archived: .is_archived, type: .type}]"
JQ_FLAG_CLEANUP = (
    "[.[] | {name: .feature.name, enabled: .enabled, value: .feature_state_value, "
    "mv_count: ((.multivariate_feature_state_values // []) | length)}]"
)


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "feature_states" in data:
        return [
            {
                "name": item["feature"]["name"],
                "enabled": item.get("enabled", False),
                "value": item.get("feature_state_value"),
                "mv_count": len(item.get("multivariate_feature_state_values") or []),
                "is_archived": item["feature"].get("is_archived", False),
            }
            for item in data["feature_states"]
            if isinstance(item, dict) and "feature" in item
        ]
    return data


def analyze_stale_flags(
    root: Path,
    *,
    offline_features: Path | None = None,
    offline_flags: Path | None = None,
) -> dict[str, Any]:
    """Identify archived or 100%-enabled flags and map their code call sites."""
    code_calls = scan_python_flag_calls(root)
    calls_by_flag: dict[str, list[dict[str, Any]]] = {}
    for call in code_calls:
        calls_by_flag.setdefault(call["flag"], []).append({"file": call["file"], "line": call["line"], "method": call["method"]})

    warnings: list[str] = []
    if offline_features is not None:
        features = _load_json_list(offline_features)
    else:
        features_data, f_res = run_flagsmith_json(["feature", "list", "--include-archived"], jq_expr=JQ_FEATURE_SUMMARY, cwd=root)
        features = features_data if f_res.ok and isinstance(features_data, list) else []
        if not f_res.ok:
            warnings.append(f_res.stderr)

    if offline_flags is not None:
        flags = _load_json_list(offline_flags)
    else:
        flags_data, fl_res = run_flagsmith_json(["flag", "list"], jq_expr=JQ_FLAG_CLEANUP, cwd=root)
        flags = flags_data if fl_res.ok and isinstance(flags_data, list) else []
        if not fl_res.ok:
            warnings.append(fl_res.stderr)

    archived_names = {f["name"] for f in features if f.get("is_archived")}
    cleanup_candidates: list[dict[str, Any]] = []

    for flag in flags:
        name = flag.get("name")
        if not name:
            continue
        sites = calls_by_flag.get(name, [])
        if name in archived_names and sites:
            cleanup_candidates.append(
                {
                    "flag": name,
                    "reason": "archived_in_flagsmith_still_in_code",
                    "code_sites": sites,
                    "action": "remove_dead_branch_and_run_pytest",
                }
            )
        elif flag.get("enabled") and flag.get("mv_count", 0) == 0 and sites:
            cleanup_candidates.append(
                {
                    "flag": name,
                    "reason": "fully_enabled_single_variant",
                    "code_sites": sites,
                    "action": "verify_100pct_rollout_then_inline_and_archive",
                    "archive_command": format_command(["feature", "update", name, "--archive", "--yes", "--no-input"]),
                }
            )
        elif not sites and name not in archived_names:
            cleanup_candidates.append(
                {
                    "flag": name,
                    "reason": "unused_in_code",
                    "code_sites": [],
                    "action": "archive_feature_if_retired",
                    "archive_command": format_command(["feature", "update", name, "--archive", "--yes", "--no-input"]),
                }
            )

    return {
        "phase": "cleanup",
        "warnings": warnings,
        "cleanup_candidates": cleanup_candidates,
        "candidate_count": len(cleanup_candidates),
    }


def archive_feature(root: Path, feature: str, *, apply: bool = False) -> tuple[dict[str, Any], int]:
    """Dry-run or execute archiving a retired feature in Flagsmith."""
    cmd = ["feature", "update", feature, "--archive", "--yes", "--no-input"]
    if not apply:
        return {
            "phase": "cleanup",
            "mode": "dry_run",
            "feature": feature,
            "planned_command": format_command(cmd),
        }, 0

    res = run_flagsmith(cmd, cwd=root)
    return {
        "phase": "cleanup",
        "mode": "apply",
        "feature": feature,
        "archived": res.ok,
        "stderr": res.stderr if not res.ok else "",
    }, 0 if res.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect stale Flagsmith flags and archive safely")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--offline-features", type=Path, default=None)
    parser.add_argument("--offline-flags", type=Path, default=None)
    parser.add_argument("--archive-feature", default=None, help="Feature name to archive")
    parser.add_argument("--apply", action="store_true", help="Execute archive mutation (default is dry-run)")
    args = parser.parse_args()

    root = args.project_root.resolve()
    if args.archive_feature:
        payload, code = archive_feature(root, args.archive_feature, apply=args.apply)
        emit_json(payload)
        return code

    payload = analyze_stale_flags(
        root,
        offline_features=args.offline_features,
        offline_flags=args.offline_flags,
    )
    emit_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
