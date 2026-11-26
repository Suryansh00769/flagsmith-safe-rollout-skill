# Flagsmith CLI v2+ Cheat Sheet (On-Demand Reference)

Load this file only when exact CLI syntax or `--jq` expressions are needed.

## Headless / CI Auth
- Interactive local session: `flagsmith login` (stores credentials in OS keychain).
- Headless / CI / Sandbox: set `FLAGSMITH_API_KEY=<master-api-key>` and pass `--no-input` on every command.

## Token-Efficient `--jq` Projections

```bash
# Minimal active flag states (~85-95% smaller than full API payload)
flagsmith flag list --no-input --jq '[.[] | {name: .feature.name, enabled, value: .feature_state_value}]'

# Project features including archived status
flagsmith feature list --include-archived --no-input --jq '[.[] | {id, name, is_archived, type}]'

# Single flag evaluation for CI gating (exits non-zero if disabled)
flagsmith eval my_feature --identity ci-smoke --trait plan=pro --test --no-input

# Local SDK snapshot for offline fallback
flagsmith environment document --no-input > env.json

# Count feature states without dumping payload
flagsmith environment document --no-input --jq '{env: .name, features: (.feature_states | length)}'
```

## Safe Rollout & Rollback Commands

```bash
# Create standard flag (off by default)
flagsmith feature create my_feature --description "Safe rollout guard" --no-input

# Create multivariate feature with weighted variants
flagsmith feature create pricing_v2 --variants '[{"value":"control","weight":90},{"value":"candidate","weight":10}]' --no-input

# Shift weights for progressive rollout
flagsmith flag update pricing_v2 --weight control=50 --weight candidate=50 --no-input

# Instant emergency rollback
flagsmith flag disable pricing_v2 --yes --no-input

# Archive feature after dead-code removal
flagsmith feature update pricing_v2 --archive --yes --no-input
```

## Python SDK Offline / Fallback Pattern

```python
from flagsmith import Flagsmith
from flagsmith.models import DefaultFlag
from flagsmith.offline_handlers import LocalFileHandler

client = Flagsmith(
    environment_key=env_key,
    request_timeout_seconds=3,
    default_flag_handler=lambda name: DefaultFlag(enabled=False, value=None),
    offline_handler=LocalFileHandler("env.json"),  # optional local recovery
)
```
