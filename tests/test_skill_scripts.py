"""Tests for Flagsmith Safe Rollout skill scripts and token benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "flagsmith-safe-rollout" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
sys.path.insert(0, str(ROOT))

from benchmark_tokens import run_benchmark  # noqa: E402
from cleanup_stale import analyze_stale_flags, archive_feature  # noqa: E402
from preflight import run_preflight  # noqa: E402
from rollout_guard import build_rollout_commands, execute_rollout, parse_variants  # noqa: E402
from scan_flags import run_scan  # noqa: E402


SAMPLE_DOC = ROOT / "demo_app" / "sample_env_document.json"


def test_preflight_offline_doc_detects_dev_and_features() -> None:
    res = run_preflight(ROOT, offline_doc_path=SAMPLE_DOC)
    assert res["ready"] is True
    assert res["flagsmith_json_present"] is True
    assert res["project_id"] == 56360
    assert res["environment"]["environment_name"] == "Development"
    assert res["environment"]["is_production"] is False
    assert res["environment"]["feature_count"] == 2


def test_preflight_flags_production_env(tmp_path: Path) -> None:
    (tmp_path / "flagsmith.json").write_text('{"project": 1, "environment": "abc"}', encoding="utf-8")
    prod_doc = tmp_path / "prod.json"
    prod_doc.write_text('{"name": "Production", "feature_states": []}', encoding="utf-8")

    res = run_preflight(tmp_path, offline_doc_path=prod_doc)
    assert res["environment"]["is_production"] is True
    assert res["environment"]["requires_confirm_prod"] is True


def test_scan_flags_detects_missing_fallback_and_diff_suggestions(tmp_path: Path) -> None:
    src = tmp_path / "service.py"
    src.write_text(
        'def run(client):\n    if client.has_feature("unwrapped_beta"):\n        return 1\n    return 0\n',
        encoding="utf-8",
    )
    patch = tmp_path / "change.patch"
    patch.write_text(
        "+++ b/billing.py\n+def apply_instant_refund(order_id: str) -> None:\n+    pass\n",
        encoding="utf-8",
    )
    flags_json = tmp_path / "flags.json"
    flags_json.write_text(
        json.dumps([{"name": "unused_remote_flag", "enabled": True, "value": None}]),
        encoding="utf-8",
    )

    res = run_scan(tmp_path, diff_file=patch, offline_flags=flags_json)
    assert len(res["missing_fallback_in_code"]) == 1
    assert res["missing_fallback_in_code"][0]["flag"] == "unwrapped_beta"
    assert res["missing_in_flagsmith"] == ["unwrapped_beta"]
    assert res["unused_in_code"] == ["unused_remote_flag"]
    assert res["unflagged_diff_symbols"][0]["suggested_flag"] == "enable_apply_instant_refund"


def test_rollout_guard_dry_run_and_variant_validation() -> None:
    variants = parse_variants("control=90,v2=10")
    assert variants == [{"value": "control", "weight": 90}, {"value": "v2", "weight": 10}]

    with pytest.raises(ValueError, match="sum to 100"):
        parse_variants("control=80,v2=10")

    payload, code = execute_rollout(
        ROOT,
        feature="checkout_v2_pricing",
        description="Gradual checkout rollout",
        variants_spec="control=90,v2=10",
        eval_identity="user-42",
        eval_traits=["plan=pro"],
        apply=False,
    )
    assert code == 0
    assert payload["mode"] == "dry_run"
    assert payload["applied"] is False
    assert payload["rollback_command"] == "flagsmith flag disable checkout_v2_pricing --yes --no-input"
    assert any("evaluate checkout_v2_pricing --identity user-42 --test" in cmd for cmd in payload["planned_commands"])


def test_build_rollout_commands_rejects_bad_feature_name() -> None:
    with pytest.raises(ValueError, match="Feature name"):
        build_rollout_commands(
            feature="Bad Name!",
            description="invalid",
            variants=[],
            segment=None,
            enable=True,
            eval_identity=None,
            eval_traits=[],
            feature_exists=False,
        )


def test_cleanup_stale_finds_fully_enabled_and_archived_candidates(tmp_path: Path) -> None:
    code = tmp_path / "feature_user.py"
    code.write_text(
        'def check(client):\n    return client.evaluate("legacy_promo_banner", default_enabled=False)\n'
        '# simulate standard sdk call\n'
        'def check2(sdk):\n    return sdk.has_feature("legacy_promo_banner", default=False)\n',
        encoding="utf-8",
    )
    features_file = tmp_path / "features.json"
    features_file.write_text(json.dumps([{"name": "legacy_promo_banner", "is_archived": True, "type": "STANDARD"}]), encoding="utf-8")
    flags_file = tmp_path / "flags.json"
    flags_file.write_text(json.dumps([{"name": "legacy_promo_banner", "enabled": True, "value": "Hi", "mv_count": 0}]), encoding="utf-8")

    res = analyze_stale_flags(tmp_path, offline_features=features_file, offline_flags=flags_file)
    assert res["candidate_count"] == 1
    assert res["cleanup_candidates"][0]["reason"] == "archived_in_flagsmith_still_in_code"

    dry_archive, code_num = archive_feature(tmp_path, "legacy_promo_banner", apply=False)
    assert code_num == 0
    assert dry_archive["mode"] == "dry_run"
    assert "--archive --yes --no-input" in dry_archive["planned_command"]


def test_token_benchmark_achieves_substantial_savings() -> None:
    bench = run_benchmark(ROOT, flag_count=25)
    assert bench["jq_reduction_pct"] >= 80.0
    assert bench["skill_scan_reduction_pct"] >= 80.0
