"""Measure token-efficiency gains of Flagsmith CLI --jq + skill script summaries."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

SKILL_SCRIPTS = Path(__file__).resolve().parent / ".agents" / "skills" / "flagsmith-safe-rollout" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from scan_flags import run_scan  # noqa: E402


def estimate_tokens(text: str) -> int:
    """Approximate LLM token count (~4 chars/token for compact JSON/English)."""
    return max(1, math.ceil(len(text) / 4))


def generate_realistic_flagsmith_payload(flag_count: int = 25) -> list[dict[str, Any]]:
    """Generate a realistic Flagsmith `flagsmith flag list --json` payload for benchmarking."""
    items: list[dict[str, Any]] = []
    for idx in range(flag_count):
        name = "checkout_v2_pricing" if idx == 0 else ("legacy_promo_banner" if idx == 1 else f"experiment_flag_{idx:02d}")
        items.append(
            {
                "id": 9000 + idx,
                "feature": {
                    "id": 4000 + idx,
                    "name": name,
                    "created_date": "2026-10-01T12:00:00Z",
                    "description": f"Production feature flag #{idx} controlling rollout behavior and telemetry.",
                    "initial_value": "control" if idx == 0 else None,
                    "default_enabled": idx == 1,
                    "type": "MULTIVARIATE" if idx == 0 else "STANDARD",
                    "project": 56360,
                    "tags": [101, 102],
                    "is_archived": False,
                    "owners": [{"id": 1, "email": "dev@example.com", "first_name": "Dev", "last_name": "Owner"}],
                },
                "feature_state_value": "v2" if idx == 0 else ("Welcome2026" if idx == 1 else None),
                "environment": 12001,
                "identity": None,
                "feature_segment": None,
                "enabled": idx in (0, 1) or idx % 3 == 0,
                "multivariate_feature_state_values": (
                    [
                        {"id": 501, "multivariate_feature_option": {"id": 601, "value": "control"}, "percentage_allocation": 90.0},
                        {"id": 502, "multivariate_feature_option": {"id": 602, "value": "v2"}, "percentage_allocation": 10.0},
                    ]
                    if idx == 0
                    else []
                ),
            }
        )
    return items


def run_benchmark(project_root: Path, flag_count: int = 25) -> dict[str, Any]:
    """Compare raw CLI JSON output vs --jq projection vs skill script summary."""
    raw_payload = generate_realistic_flagsmith_payload(flag_count=flag_count)
    raw_text = json.dumps(raw_payload, indent=2)

    # Equivalent to `flagsmith flag list --jq '[.[] | {name: .feature.name, enabled, value: .feature_state_value}]'`
    jq_projected = [
        {"name": item["feature"]["name"], "enabled": item["enabled"], "value": item["feature_state_value"]}
        for item in raw_payload
    ]
    jq_text = json.dumps(jq_projected, separators=(",", ":"))

    tmp_flags = project_root / ".bench-flags.tmp.json"
    try:
        tmp_flags.write_text(jq_text, encoding="utf-8")
        scan_summary = run_scan(project_root, offline_flags=tmp_flags)
        scan_text = json.dumps(scan_summary, separators=(",", ":"))
    finally:
        if tmp_flags.exists():
            tmp_flags.unlink()

    raw_tokens = estimate_tokens(raw_text)
    jq_tokens = estimate_tokens(jq_text)
    scan_tokens = estimate_tokens(scan_text)

    return {
        "flag_count": flag_count,
        "raw_chars": len(raw_text),
        "raw_tokens_est": raw_tokens,
        "jq_chars": len(jq_text),
        "jq_tokens_est": jq_tokens,
        "jq_reduction_pct": round((1 - jq_tokens / raw_tokens) * 100, 1),
        "skill_scan_chars": len(scan_text),
        "skill_scan_tokens_est": scan_tokens,
        "skill_scan_reduction_pct": round((1 - scan_tokens / raw_tokens) * 100, 1),
    }


def main() -> int:
    root = Path(__file__).resolve().parent
    res = run_benchmark(root, flag_count=25)
    print("Flagsmith Safe Rollout - Token Efficiency Benchmark (25 flags)")
    print(f"  Raw `flagsmith flag list --json`:     {res['raw_chars']:>6} chars (~{res['raw_tokens_est']:>4} tokens)")
    print(f"  Filtered `--jq` projection:           {res['jq_chars']:>6} chars (~{res['jq_tokens_est']:>4} tokens) -> {res['jq_reduction_pct']}% saved")
    print(f"  Skill `scan_flags.py` audit summary:  {res['skill_scan_chars']:>6} chars (~{res['skill_scan_tokens_est']:>4} tokens) -> {res['skill_scan_reduction_pct']}% saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
