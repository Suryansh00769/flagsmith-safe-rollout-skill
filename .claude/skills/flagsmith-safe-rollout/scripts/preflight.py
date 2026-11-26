"""Phase 1: Preflight check for Flagsmith CLI, config, auth, and environment safety."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from _cli import (
    emit_json,
    find_flagsmith_bin,
    load_flagsmith_config,
    run_flagsmith,
    run_flagsmith_json,
)


def _detect_env_safety(env_name: str | None) -> dict[str, Any]:
    name = (env_name or "unknown").strip()
    is_prod = "prod" in name.lower()
    return {
        "environment_name": name,
        "is_production": is_prod,
        "requires_confirm_prod": is_prod,
    }


def run_preflight(
    project_root: Path,
    *,
    offline_doc_path: Path | None = None,
    snapshot_out: Path | None = None,
) -> dict[str, Any]:
    """Collect minimal, token-efficient preflight diagnostics."""
    cfg = load_flagsmith_config(project_root)
    cli_bin = find_flagsmith_bin()
    has_api_key = bool(os.environ.get("FLAGSMITH_API_KEY"))

    cli_version = None
    if cli_bin:
        ver = run_flagsmith(["--version"], cwd=project_root, no_input=False)
        if ver.ok:
            cli_version = ver.stdout.splitlines()[0]

    env_meta: dict[str, Any] = {"environment_name": "unknown", "is_production": False, "requires_confirm_prod": False}
    auth_ok = False
    auth_source = "FLAGSMITH_API_KEY" if has_api_key else "os_keychain"
    auth_hint = None
    snapshot_saved = None

    if offline_doc_path is not None:
        doc = json.loads(offline_doc_path.read_text(encoding="utf-8"))
        env_meta = _detect_env_safety(doc.get("name"))
        auth_source = "offline_document"
        auth_ok = True
        env_meta["feature_count"] = len(doc.get("feature_states", []))
    else:
        auth_res = run_flagsmith(["auth", "status"], cwd=project_root)
        auth_ok = auth_res.ok
        if not auth_res.ok:
            auth_hint = (
                "Set FLAGSMITH_API_KEY for headless/CI runs or run 'flagsmith login' in a desktop terminal."
                if auth_res.error_kind == "auth_unavailable"
                else auth_res.stderr
            )

        if auth_ok:
            summary, doc_res = run_flagsmith_json(
                ["environment", "document"],
                jq_expr="{name: .name, feature_count: (.feature_states | length)}",
                cwd=project_root,
            )
            if doc_res.ok and isinstance(summary, dict):
                env_meta = _detect_env_safety(summary.get("name"))
                env_meta["feature_count"] = summary.get("feature_count", 0)

            if snapshot_out is not None:
                raw_doc = run_flagsmith(["environment", "document"], cwd=project_root)
                if raw_doc.ok:
                    snapshot_out.write_text(raw_doc.stdout + "\n", encoding="utf-8")
                    snapshot_saved = str(snapshot_out)

    ready = bool(cfg and cli_bin and auth_ok)
    return {
        "phase": "preflight",
        "ready": ready,
        "flagsmith_json_present": cfg is not None,
        "project_id": cfg.get("project") if cfg else None,
        "environment_key": cfg.get("environment") if cfg else None,
        "cli_found": cli_bin is not None,
        "cli_version": cli_version,
        "auth_ok": auth_ok,
        "auth_source": auth_source,
        "auth_hint": auth_hint,
        "environment": env_meta,
        "snapshot_saved": snapshot_saved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Flagsmith Safe Rollout preflight check")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--offline-doc", type=Path, default=None, help="Offline environment document JSON")
    parser.add_argument("--snapshot-out", type=Path, default=None, help="Write environment document backup")
    args = parser.parse_args()

    result = run_preflight(
        args.project_root.resolve(),
        offline_doc_path=args.offline_doc,
        snapshot_out=args.snapshot_out,
    )
    emit_json(result)
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
