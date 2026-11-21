"""Shared setup for Assist tests.

If the real app.core.* modules don't exist (running this pack on its own), tiny stubs are installed so
app.capture.adapters (reused by Assist) can be imported. In the real repo the real modules are used.
"""
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
    config.addinivalue_line("markers", "integration: needs real Supabase + Groq")
    config.addinivalue_line("markers", "pg: needs a throwaway local Postgres (KAARIGAR_TEST_PG_DSN)")
