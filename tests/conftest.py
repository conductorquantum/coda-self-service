"""Shared test fixtures."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

config_module = importlib.import_module("self_service.server.config")


@pytest.fixture(autouse=True)
def _isolate_persisted_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent tests from reading or writing real persisted state."""
    monkeypatch.setattr(
        config_module, "PERSISTED_CONFIG_PATH", tmp_path / "coda.config"
    )
    monkeypatch.setattr(
        config_module, "PERSISTED_PRIVATE_KEY_PATH", tmp_path / "coda-private-key"
    )
