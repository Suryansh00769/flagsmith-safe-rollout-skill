"""Phase 3: Safe progressive rollout planner/executor with dry-run guard and eval gate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _cli import emit_json, format_command, run_flagsmith, run_flagsmith_json

FEATURE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")


def parse_variants(spec: str | None) -> list[dict[str, Any]]:
    """Parse 'control=90,v2=10' into Flagsmith variant payloads and validate sum == 100."""
    if not spec:
        return []
    variants: list[dict[str, Any]] = []
    total = 0
    for part in spec.split(","):
        chunk = part.strip()
        if "=" not in chunk:
            raise ValueError(f"Invalid variant spec '{chunk}'; expected key=weight")
        key, raw_weight = chunk.split("=", 1)
        weight = int(raw_weight.strip())
        if weight < 0 or weight > 100:
            raise ValueError(f"Weight for '{key}' must be between 0 and 100")
        variants.append({"value": key.strip(), "weight": weight})
        total += weight
    if total != 100:
        raise ValueError(f"Variant weights must sum to 100, got {total}")
    return variants


def _resolve_variant_weights(
    project_root: Path,
    feature: str,
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map requested variant keys/values to Flagsmith variant key or numeric id."""
    if not variants:
        return []
    listed, res = run_flagsmith_json(
        ["feature", "variant", "list", feature],
        jq_expr="[.[] | {id: .id, key: .key, value: .value}]",
        cwd=project_root,
    )
    if not res.ok or not isinstance(listed, list):
        return variants

    lookup: dict[str, str] = {}
    for item in listed:
        if not isinstance(item, dict):
            continue
        ident = item.get("key") or item.get("id")
        if ident is None:
            continue
        ident_str = str(ident)
        if item.get("key"):
            lookup[str(item["key"])] = ident_str
        if item.get("value") is not None:
            lookup[str(item["value"])] = ident_str
        if item.get("id") is not None:
            lookup[str(item["id"])] = ident_str

    return [
        {**variant, "selector": lookup.get(str(variant["value"]), str(variant["value"]))}
        for variant in variants
    ]


def build_rollout_commands(
    *,
    feature: str,
    description: str,
    variants: list[dict[str, Any]],
    segment: str | None,
    enable: bool,
    eval_identity: str | None,
    eval_traits: list[str],
    feature_exists: bool,
) -> tuple[list[list[str]], list[str]]:
    """Build deterministic Flagsmith CLI v2 commands and an instant rollback command."""
    if not FEATURE_RE.match(feature):
        raise ValueError("Feature name must be lowercase alphanumeric/underscore/hyphen (2-63 chars)")

    commands: list[list[str]] = []
    if not feature_exists:
        create_cmd = ["feature", "create", feature, "--description", description]
        if variants:
            payload = [{"value": v["value"], "weight": v["weight"]} for v in variants]
            create_cmd.extend(["--variants", json.dumps(payload, separators=(",", ":"))])
        elif enable:
            create_cmd.append("--enabled")
        commands.append(create_cmd)

    if feature_exists or variants or segment:
        update_cmd = ["flag", "update", feature]
        update_cmd.append("--enable" if enable else "--disable")
        if segment:
            update_cmd.extend(["--segment", segment])
        if (feature_exists or segment) and variants:
            for variant in variants:
                selector = variant.get("selector", variant["value"])
                update_cmd.extend(["--weight", f"{selector}={variant['weight']}"])
        update_cmd.append("--yes")
        commands.append(update_cmd)

    if eval_identity:
        eval_cmd = ["evaluate", feature, "--identity", eval_identity, "--test"]
        for trait in eval_traits:
            eval_cmd.extend(["--trait", trait])
        commands.append(eval_cmd)

    rollback_cmd = ["flag", "disable", feature, "--yes", "--no-input"]
    if segment:
        rollback_cmd.extend(["--segment", segment])
    return commands, rollback_cmd


def execute_rollout(
    project_root: Path,
    *,
    feature: str,
    description: str,
    variants_spec: str | None = None,
    segment: str | None = None,
    enable: bool = True,
    eval_identity: str | None = None,
    eval_traits: list[str] | None = None,
    apply: bool = False,
    confirm_prod: bool = False,
    assume_exists: bool = False,
) -> tuple[dict[str, Any], int]:
    """Plan (--dry-run) or execute (--apply) a safe Flagsmith rollout."""
    variants = parse_variants(variants_spec)
    traits = eval_traits or []

    feature_exists = assume_exists
    env_is_prod = False
    if apply:
        env_doc, doc_res = run_flagsmith_json(
            ["environment", "document"],
            jq_expr="{name: .name}",
            cwd=project_root,
        )
        if doc_res.ok and isinstance(env_doc, dict):
            env_is_prod = "prod" in str(env_doc.get("name", "")).lower()
        if env_is_prod and not confirm_prod:
            return {
                "phase": "rollout_guard",
                "applied": False,
                "blocked": "Target environment looks like Production. Re-run with --confirm-prod after snapshot.",
            }, 2

        existing, feat_res = run_flagsmith_json(
            ["feature", "list"],
            jq_expr=f'[.[] | select(.name == "{feature}") | .name]',
            cwd=project_root,
        )
        if feat_res.ok and isinstance(existing, list):
            feature_exists = feature in existing

        if feature_exists and variants:
            variants = _resolve_variant_weights(project_root, feature, variants)

    commands, rollback_cmd = build_rollout_commands(
        feature=feature,
        description=description,
        variants=variants,
        segment=segment,
        enable=enable,
        eval_identity=eval_identity,
        eval_traits=traits,
        feature_exists=feature_exists,
    )

    executed: list[dict[str, Any]] = []
    if apply:
        for cmd in commands:
            if not feature_exists and segment and variants and cmd[:2] == ["flag", "update"]:
                resolved_variants = _resolve_variant_weights(project_root, feature, variants)
                rebuilt, _ = build_rollout_commands(
                    feature=feature,
                    description=description,
                    variants=resolved_variants,
                    segment=segment,
                    enable=enable,
                    eval_identity=None,
                    eval_traits=[],
                    feature_exists=True,
                )
                cmd = rebuilt[0]
            res = run_flagsmith(cmd, cwd=project_root)
            executed.append({"command": format_command(cmd), "ok": res.ok, "returncode": res.returncode, "stderr": res.stderr})
            if not res.ok:
                return {
                    "phase": "rollout_guard",
                    "applied": False,
                    "feature": feature,
                    "executed": executed,
                    "rollback_command": format_command(rollback_cmd),
                }, 1

    return {
        "phase": "rollout_guard",
        "mode": "apply" if apply else "dry_run",
        "applied": apply,
        "feature": feature,
        "variants": variants,
        "planned_commands": [format_command(cmd) for cmd in commands],
        "executed": executed if apply else None,
        "rollback_command": format_command(rollback_cmd),
    }, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Flagsmith rollout planner and executor")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--feature", required=True)
    parser.add_argument("--description", default="Safe rollout managed by flagsmith-safe-rollout skill")
    parser.add_argument("--variants", default=None, help="Comma-separated weights, e.g. control=90,v2=10")
    parser.add_argument("--segment", default=None, help="Optional segment ID or name")
    parser.add_argument("--disable", action="store_true", help="Disable flag instead of enabling")
    parser.add_argument("--eval-identity", default=None, help="Run flagsmith evaluate --test for this identity")
    parser.add_argument("--eval-trait", action="append", default=[], help="Trait key=value for evaluate")
    parser.add_argument("--apply", action="store_true", help="Execute planned CLI commands (default is dry-run)")
    parser.add_argument("--confirm-prod", action="store_true", help="Required if target environment is Production")
    args = parser.parse_args()

    try:
        payload, code = execute_rollout(
            args.project_root.resolve(),
            feature=args.feature,
            description=args.description,
            variants_spec=args.variants,
            segment=args.segment,
            enable=not args.disable,
            eval_identity=args.eval_identity,
            eval_traits=args.eval_trait,
            apply=args.apply,
            confirm_prod=args.confirm_prod,
        )
    except ValueError as exc:
        emit_json({"phase": "rollout_guard", "applied": False, "error": str(exc)})
        return 2

    emit_json(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
