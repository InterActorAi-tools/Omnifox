"""Tests for the bootstrap_lock context manager in database.py.

The lock helper exists to serialize startup work across gunicorn workers when
running on Postgres. On SQLite it must be a no-op (single writer at the
filesystem level already serializes), so importing and using it from
SQLite-backed tests must never raise.
"""
from __future__ import annotations


class TestBootstrapLockOnSQLite:
    """The default test config uses SQLite, so these tests exercise the
    no-op branch directly."""

    def test_lock_context_does_not_raise_on_sqlite(self):
        from database import bootstrap_lock
        with bootstrap_lock():
            pass  # no exception = pass

    def test_lock_context_can_be_reentered_sequentially(self):
        from database import bootstrap_lock
        with bootstrap_lock():
            pass
        with bootstrap_lock():
            pass

    def test_run_with_bootstrap_lock_returns_callable_result(self):
        from database import run_with_bootstrap_lock
        result = run_with_bootstrap_lock(lambda: 42)
        assert result == 42

    def test_exception_inside_lock_propagates(self):
        import pytest
        from database import bootstrap_lock

        with pytest.raises(RuntimeError, match="boom"):
            with bootstrap_lock():
                raise RuntimeError("boom")

    def test_lock_module_attributes_present(self):
        """Smoke check that the public surface exists and is wired."""
        import database
        assert callable(database.bootstrap_lock)
        assert callable(database.run_with_bootstrap_lock)
        # Lock key is a positive 64-bit signed int.
        assert isinstance(database._BOOTSTRAP_LOCK_KEY, int)
        assert 0 < database._BOOTSTRAP_LOCK_KEY < 2 ** 63
