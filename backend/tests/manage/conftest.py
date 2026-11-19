"""Shared setup for Phase 4 tests: tiny stubs if app.core.* isn't importable (pack run on its own)."""
import importlib
import sys
import types


def _ensure_stub(name: str, **attrs):
    try:
        importlib.import_module(name)
    except Exception:  # noqa: BLE001
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod


_ensure_stub("app.core")
_ensure_stub("app.core.auth", get_current_user=lambda: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "pg: needs a throwaway local Postgres (KAARIGAR_TEST_PG_DSN)")
