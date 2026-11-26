"""Resilient Flagsmith SDK wrapper with offline snapshot and safe fallback defaults."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flagsmith import Flagsmith
from flagsmith.models import DefaultFlag
from flagsmith.offline_handlers import LocalFileHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlagEvaluation:
    """Resolved flag state with provenance for observability and safety audits."""

    feature: str
    enabled: bool
    value: Any
    source: str


class SafeFlagClient:
    """Wraps Flagsmith SDK with strict timeouts, offline snapshot support, and safe fallbacks."""

    def __init__(
        self,
        *,
        environment_key: str | None = None,
        offline_doc_path: Path | None = None,
        request_timeout_seconds: int = 2,
    ) -> None:
        self._offline_doc_path = offline_doc_path
        self._env_key = environment_key or os.environ.get("FLAGSMITH_ENVIRONMENT_KEY")
        self._client: Flagsmith | None = None

        default_handler = lambda name: DefaultFlag(enabled=False, value=None, is_default=True)

        if offline_doc_path is not None and offline_doc_path.is_file():
            self._client = Flagsmith(
                offline_mode=True,
                offline_handler=LocalFileHandler(str(offline_doc_path)),
            )
            self._base_source = "flagsmith_offline_doc"
        elif self._env_key:
            self._client = Flagsmith(
                environment_key=self._env_key,
                request_timeout_seconds=request_timeout_seconds,
                default_flag_handler=default_handler,
            )
            self._base_source = "flagsmith_live"
        else:
            self._base_source = "safe_fallback"

    def evaluate(
        self,
        feature_name: str,
        *,
        identity: str | None = None,
        traits: dict[str, Any] | None = None,
        default_enabled: bool = False,
        default_value: Any = None,
    ) -> FlagEvaluation:
        """Evaluate a flag safely; never raises on Flagsmith API failure."""
        if self._client is None:
            return FlagEvaluation(
                feature=feature_name,
                enabled=default_enabled,
                value=default_value,
                source="safe_fallback",
            )

        try:
            flags = (
                self._client.get_identity_flags(identifier=identity, traits=traits or {})
                if identity
                else self._client.get_environment_flags()
            )
            flag = flags.get_flag(feature_name)
            if getattr(flag, "is_default", False):
                return FlagEvaluation(
                    feature=feature_name,
                    enabled=default_enabled,
                    value=default_value,
                    source="safe_fallback",
                )
            return FlagEvaluation(
                feature=feature_name,
                enabled=bool(flag.enabled),
                value=flag.value,
                source=self._base_source,
            )
        except Exception as exc:  # noqa: BLE001 - intentional fail-safe boundary
            logger.warning("Flagsmith evaluation failed for %s (%s); using safe fallback", feature_name, exc)
            return FlagEvaluation(
                feature=feature_name,
                enabled=default_enabled,
                value=default_value,
                source="safe_fallback",
            )
