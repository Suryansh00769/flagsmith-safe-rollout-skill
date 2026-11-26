"""Tests proving FastAPI demo app uses Flagsmith offline docs and falls back safely."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo_app.app import create_app  # noqa: E402
from demo_app.flag_client import SafeFlagClient  # noqa: E402

SAMPLE_DOC = ROOT / "demo_app" / "sample_env_document.json"


def _get_route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route {path} not found")


def test_demo_app_uses_offline_flagsmith_document_segment_override() -> None:
    client = SafeFlagClient(offline_doc_path=SAMPLE_DOC)
    app = create_app(flag_client=client)
    quote_endpoint = _get_route_endpoint(app, "/checkout/quote")

    body = quote_endpoint(user_id="pro-user-1", amount=100.0, plan="pro")
    assert body.pricing_engine == "v2_dynamic"
    assert body.discount_pct == 15.0
    assert body.total == 85.0
    assert body.flag_source == "flagsmith_offline_doc"
    assert body.promo_banner == "Holiday2026"


def test_demo_app_safe_fallback_when_flagsmith_unavailable() -> None:
    # No environment key and no offline doc -> simulates unreachable/unconfigured Flagsmith
    client = SafeFlagClient(environment_key=None, offline_doc_path=None)
    app = create_app(flag_client=client)
    quote_endpoint = _get_route_endpoint(app, "/checkout/quote")

    body = quote_endpoint(user_id="user-1", amount=100.0, plan="pro")
    assert body.pricing_engine == "v1_stable"
    assert body.discount_pct == 0.0
    assert body.total == 100.0
    assert body.flag_source == "safe_fallback"
    assert body.promo_banner is None


def test_demo_app_survives_broken_flagsmith_client_without_500() -> None:
    class BrokenSDK:
        def get_identity_flags(self, **_kwargs):
            raise TimeoutError("Flagsmith API timeout")

        def get_environment_flags(self):
            raise TimeoutError("Flagsmith API timeout")

    client = SafeFlagClient()
    client._client = BrokenSDK()  # type: ignore[assignment]
    app = create_app(flag_client=client)
    quote_endpoint = _get_route_endpoint(app, "/checkout/quote")
    health_endpoint = _get_route_endpoint(app, "/health")

    assert health_endpoint() == {"status": "ok"}
    body = quote_endpoint(user_id="user-2", amount=200.0, plan="pro")
    assert body.pricing_engine == "v1_stable"
    assert body.total == 200.0
    assert body.flag_source == "safe_fallback"
