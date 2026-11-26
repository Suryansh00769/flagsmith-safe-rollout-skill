---
name: flagsmith-safe-rollout
description: End-to-end feature flag lifecycle skill using Flagsmith CLI v2+: preflight checks, risky diff & fallback audits, safe progressive rollouts with instant rollback commands, and stale-flag cleanup. Use when wrapping features in Flagsmith flags, verifying flag fallbacks, gating CI with flag evaluations, or cleaning up dead flag branches.
compatibility: Requires Flagsmith CLI v2+ (flagsmith) and Python 3.10+.
---

# Flagsmith Safe Rollout & Cleanup

Manage the complete feature-flag lifecycle safely and token-efficiently using `flagsmith` CLI v2+ and the bundled Python scripts in `scripts/`.

## Core Rules (Non-Negotiable)

1. **Token efficiency first:** Never dump raw Flagsmith API responses into context. Always use the bundled scripts or `flagsmith ... --json --jq '<expr>'` with `--no-input`.
2. **Dry-run by default:** Never mutate Flagsmith state without previewing the exact commands via `--dry-run` first, then explicitly passing `--apply`.
3. **Production guardrail:** If targeting a Production environment, snapshot the environment document first (`flagsmith environment document`) and require `--confirm-prod` before applying changes.
4. **Mandatory fallback defaults:** Every feature flag call in application code must handle Flagsmith API timeouts/outages with an explicit safe fallback (`default_flag_handler` or explicit fallback argument).

---

## 4-Phase Workflow

### Phase 1: Preflight & Environment Snapshot
Verify `flagsmith.json`, CLI v2+, auth source (`FLAGSMITH_API_KEY` or OS keychain), and target environment:

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/preflight.py
```

Before risky changes, capture a local recovery snapshot (`LocalFileHandler`-compatible):

```powershell
flagsmith environment document --no-input > .flagsmith-snapshot.json
```

### Phase 2: Codebase & Diff Audit
Scan `git diff` for unflagged changes and audit existing Flagsmith SDK calls for missing fallbacks or drift against live Flagsmith flags:

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/scan_flags.py --diff-base HEAD
```

Review the compact JSON summary:
- `missing_fallback_in_code`: Wrap or add `default_flag_handler` immediately.
- `missing_in_flagsmith`: Create the flag via Phase 3 before merging code.
- `unflagged_diff_symbols`: Suggest wrapping risky new endpoints/functions behind a flag.

### Phase 3: Safe Rollout & Verification Gate
Preview a progressive rollout (default `--dry-run`, zero mutations):

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/rollout_guard.py `
  --feature checkout_v2 `
  --description "Gradual rollout for v2 checkout pricing" `
  --variants "control=90,v2=10"
```

When approved, apply and verify with `flagsmith eval --test`:

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/rollout_guard.py `
  --feature checkout_v2 `
  --description "Gradual rollout for v2 checkout pricing" `
  --variants "control=90,v2=10" `
  --eval-identity smoke-test-user `
  --apply
```

Always record the printed `rollback_command` (e.g., `flagsmith flag disable checkout_v2 --yes --no-input`).

### Phase 4: Stale Flag Detection & Cleanup
Once a flag is rolled out to 100% or archived, locate dead branches and generate a removal plan:

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/cleanup_stale.py
```

After removing dead flag branches from code and running tests (`pytest`), archive the feature in Flagsmith:

```powershell
python .agents/skills/flagsmith-safe-rollout/scripts/cleanup_stale.py --archive-feature <feature_name> --apply
```

---

## Reference Material
- Read [references/cli-cheat-sheet.md](references/cli-cheat-sheet.md) only when you need exact Flagsmith CLI v2 flags, `--jq` projections, or headless CI setup (`FLAGSMITH_API_KEY`).
