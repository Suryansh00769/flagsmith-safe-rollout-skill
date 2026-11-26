# Flagsmith Safe Rollout & Cleanup — Agent Skill (Toggle Wars Track 04)

An end-to-end, token-efficient **Agent Skill** built on **Flagsmith CLI v2+** (`flagsmith`) that guides AI coding agents safely through the entire feature-flag lifecycle: **Preflight & Snapshot → Code/Diff Audit → Guarded Progressive Rollout → Stale Flag Cleanup & Archival**.

---

## Why This Skill Exists

Most feature-flag workflows break down at two extremes:
1. **Context bloat:** Dumping raw Flagsmith API responses into an LLM context burns thousands of tokens per turn.
2. **Unsafe mutations & flag debt:** Agents mutate production flags without dry-run previews, forget SDK offline/timeout fallbacks, or leave dead `if/else` flag branches in code forever.

This skill solves both by combining **progressive disclosure** (`SKILL.md` + on-demand `references/cli-cheat-sheet.md`), **`flagsmith ... --json --jq` projections**, **mandatory `--dry-run` defaults**, and **deterministic Python lifecycle scripts**.

---

## Measured Token Efficiency

Measured via [`benchmark_tokens.py`](benchmark_tokens.py) on a 25-flag environment:

| Approach | Output Size | Est. Tokens | Savings vs. Raw |
| --- | ---: | ---: | ---: |
| Raw `flagsmith flag list --json` | 19,727 chars | ~4,932 | Baseline |
| Filtered `--jq` projection | 1,477 chars | ~370 | **92.5% saved** |
| Skill `scan_flags.py` summary | 735 chars | ~184 | **96.3% saved** |

---

## Architecture & How Flagsmith Powers It

```text
.agents/skills/flagsmith-safe-rollout/
├── SKILL.md                      # Lean 4-phase workflow instructions
├── references/cli-cheat-sheet.md # Loaded only on demand
└── scripts/
    ├── _cli.py                   # Shared Flagsmith CLI v2 wrapper (--no-input, auth classification)
    ├── preflight.py              # Verifies flagsmith.json, auth, env safety, offline snapshots
    ├── scan_flags.py             # AST + git diff audit cross-referenced with --jq live flags
    ├── rollout_guard.py          # Dry-run planner, weighted variants, eval --test gate, rollback cmd
    └── cleanup_stale.py          # Detects 100%-enabled/archived flags & prepares safe archival
```

If you remove Flagsmith from this repo, the core lifecycle engine stops working: every phase relies on `flagsmith.json`, `flagsmith` CLI v2+ (`feature`, `flag`, `evaluate --test`, `environment document`, `--jq`, `--no-input`), and the Python SDK (`Flagsmith` + `LocalFileHandler` + `DefaultFlag`) in [`demo_app/`](demo_app/).

---

## Quickstart

### 1. Prerequisites
- **Flagsmith CLI v2+:** `irm https://raw.githubusercontent.com/Flagsmith/flagsmith-cli/main/install.ps1 | iex` (Windows) or `curl -fsSL https://get.flagsmith.com | sh` (macOS/Linux)
- **Python 3.10+**

### 2. Setup Environment & Tests
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe benchmark_tokens.py
```

### 3. Connect to Your Flagsmith Project
```powershell
flagsmith init
# For headless CI / sandboxed agents:
$env:FLAGSMITH_API_KEY = "<your-master-api-key>"
```

### 4. Mirror Skill to Claude Code / Cursor / Codex (Optional)
```powershell
.venv\Scripts\python.exe install_skill.py --targets claude cursor codex
```

---

## 4-Phase Demo Walkthrough (2–3 Min Video Guide)

1. **Phase 1 — Preflight & Snapshot (20s):**
   ```powershell
   .venv\Scripts\python.exe .agents\skills\flagsmith-safe-rollout\scripts\preflight.py --offline-doc demo_app\sample_env_document.json
   ```
   Verifies `flagsmith.json`, CLI v2+, auth source, and production guardrails.
2. **Phase 2 — Audit Codebase & Risky Diffs (35s):**
   ```powershell
   .venv\Scripts\python.exe .agents\skills\flagsmith-safe-rollout\scripts\scan_flags.py --offline-flags demo_app\sample_env_document.json
   ```
   Cross-references Python AST call sites and `git diff` against Flagsmith flags using `--jq`.
3. **Phase 3 — Guarded Progressive Rollout + Rollback (45s):**
   ```powershell
   .venv\Scripts\python.exe .agents\skills\flagsmith-safe-rollout\scripts\rollout_guard.py --feature checkout_v2_pricing --variants control=90,v2=10 --eval-identity user-1
   ```
   Previews exact `flagsmith feature create`, `flagsmith flag update --weight`, `flagsmith evaluate --test`, and prints the instant `flagsmith flag disable` rollback command. Add `--apply` when ready to execute live.
4. **Phase 4 — Stale Flag Cleanup & Token Proof (40s):**
   ```powershell
   .venv\Scripts\python.exe .agents\skills\flagsmith-safe-rollout\scripts\cleanup_stale.py --offline-features demo_app\sample_env_document.json --offline-flags demo_app\sample_env_document.json
   .venv\Scripts\python.exe benchmark_tokens.py
   ```
   Pinpoints `legacy_promo_banner` at `demo_app/app.py:58` for dead-code removal and Flagsmith archival, then proves 92–96% token savings.
