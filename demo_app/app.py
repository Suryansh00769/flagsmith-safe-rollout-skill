"""FastAPI demo service demonstrating safe Flagsmith rollouts and fallback defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from demo_app.flag_client import SafeFlagClient


class QuoteResponse(BaseModel):
    user_id: str
    subtotal: float
    discount_pct: float
    total: float
    pricing_engine: str
    flag_source: str
    promo_banner: str | None = Field(default=None)


def create_app(flag_client: SafeFlagClient | None = None) -> FastAPI:
    """Create the demo FastAPI application with an injectable SafeFlagClient."""
    app = FastAPI(title="Flagsmith Safe Rollout Demo", version="0.1.0")

    if flag_client is None:
        env_doc = os.environ.get("FLAGSMITH_OFFLINE_DOC")
        flag_client = SafeFlagClient(
            offline_doc_path=Path(env_doc) if env_doc else None,
        )
    app.state.flag_client = flag_client

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/checkout/quote", response_model=QuoteResponse)
    def checkout_quote(
        user_id: str = Query(..., min_length=1),
        amount: float = Query(..., gt=0),
        plan: str = Query(default="free"),
    ) -> QuoteResponse:
        client: SafeFlagClient = app.state.flag_client

        # Guarded progressive rollout with mandatory safe fallback to v1 pricing
        pricing_flag = client.evaluate(
            "checkout_v2_pricing",
            identity=user_id,
            traits={"plan": plan},
            default_enabled=False,
            default_value="control",
        )

        # Example secondary flag used to demonstrate stale-flag audit/cleanup
        promo_flag = client.evaluate(
            "legacy_promo_banner",
            default_enabled=False,
            default_value="",
        )

        if pricing_flag.enabled and pricing_flag.value == "v2":
            discount_pct = 15.0 if plan == "pro" else 5.0
            pricing_engine = "v2_dynamic"
        else:
            discount_pct = 0.0
            pricing_engine = "v1_stable"

        total = round(amount * (1.0 - discount_pct / 100.0), 2)
        banner = str(promo_flag.value) if promo_flag.enabled and promo_flag.value else None

        return QuoteResponse(
            user_id=user_id,
            subtotal=round(amount, 2),
            discount_pct=discount_pct,
            total=total,
            pricing_engine=pricing_engine,
            flag_source=pricing_flag.source,
            promo_banner=banner,
        )

    return app


app = create_app()
