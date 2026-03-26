"""Tests for executor loading (factory, auto-discovery, and noop fallback)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from coda_node.errors import ExecutorError
from coda_node.server import executor as executor_module
from coda_node.server.executor import NoopExecutor, load_executor


class TestExplicitFactory:
    def test_executor_factory_import_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.setenv(
            "CODA_EXECUTOR_FACTORY",
            "coda_node.server.executor:NoopExecutor",
        )

        from coda_node.server.config import Settings

        settings = Settings()
        executor = load_executor(settings)
        assert hasattr(executor, "run")

    def test_explicit_factory_wins_over_discovery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.setenv(
            "CODA_EXECUTOR_FACTORY",
            "coda_node.server.executor:NoopExecutor",
        )

        fake_discovered = ["some_other.executor_factory:create_executor"]
        with patch.object(
            executor_module,
            "_discover_executor_factories",
            return_value=fake_discovered,
        ):
            from coda_node.server.config import Settings

            settings = Settings()
            executor = load_executor(settings)
            assert hasattr(executor, "run")

    def test_bad_factory_path_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_EXECUTOR_FACTORY", "nonexistent.module:factory")

        from coda_node.server.config import Settings

        settings = Settings()
        with pytest.raises((ExecutorError, ModuleNotFoundError)):
            load_executor(settings)

    def test_malformed_factory_path_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.setenv("CODA_EXECUTOR_FACTORY", "no_colon_here")

        from coda_node.server.config import Settings

        settings = Settings()
        with pytest.raises(ExecutorError, match="must look like"):
            load_executor(settings)


class TestAutoDiscovery:
    def test_single_discovered_factory_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        with patch.object(
            executor_module,
            "_discover_executor_factories",
            return_value=["coda_node.server.executor:NoopExecutor"],
        ):
            from coda_node.server.config import Settings

            settings = Settings()
            executor = load_executor(settings)
            assert hasattr(executor, "run")

    def test_multiple_discovered_factories_falls_back_to_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        with patch.object(
            executor_module,
            "_discover_executor_factories",
            return_value=[
                "pkg_a.executor_factory:create_executor",
                "pkg_b.executor_factory:create_executor",
            ],
        ):
            from coda_node.server.config import Settings

            settings = Settings()
            executor = load_executor(settings)
            assert isinstance(executor, NoopExecutor)

    def test_zero_discovered_factories_falls_back_to_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODA_NODE_TOKEN", "test-token")
        monkeypatch.delenv("CODA_EXECUTOR_FACTORY", raising=False)

        with patch.object(
            executor_module,
            "_discover_executor_factories",
            return_value=[],
        ):
            from coda_node.server.config import Settings

            settings = Settings()
            executor = load_executor(settings)
            assert isinstance(executor, NoopExecutor)
