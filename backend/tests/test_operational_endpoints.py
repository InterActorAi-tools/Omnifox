"""Operational endpoints must not leak internals (E6)."""
from fastapi.testclient import TestClient


def _client():
    import main
    return TestClient(main.app)


def test_health_reveals_nothing():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_recon_endpoints_are_gone():
    client = _client()
    for path in ("/test", "/api/info", "/api/health"):
        assert client.get(path).status_code == 404, path


def test_removed_unused_endpoints_are_gone():
    # GET on a path that still exists under another method would be 405.
    client = _client()
    for path in (
        "/", "/config.js", "/assets/index.js",
        "/api/upload/process_sync/a", "/api/upload/list/a", "/api/upload/delete_file/a/b", "/api/upload/health",
        "/api/extraction/quick_status/t", "/api/extraction/batch_status", "/api/extraction/validate_url/a",
        "/api/extraction/cached_urls", "/api/extraction/extraction_stats", "/api/extraction/health",
        "/api/extraction/extract_url_cached/a",
        "/api/tasks/client/a", "/api/tasks/health",
        "/api/analytics/simple-stats-range", "/api/analytics/presets", "/api/analytics/time-series",
        "/api/analytics/clear-data", "/api/analytics/health",
        "/api/admin/users/1/logout-all", "/api/admin/users/1/set-password",
    ):
        assert client.get(path).status_code == 404, path


def test_cleanup_loop_sleeps_even_when_retention_fails(monkeypatch):
    import asyncio
    import main

    calls, sleeps = [], []

    def failing_retention():
        calls.append(1)
        raise RuntimeError("database is down")

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError  # stop after the first iteration

    monkeypatch.setattr(main, "_apply_retention", failing_retention)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    asyncio.run(main.cleanup_task())
    assert calls == [1] and sleeps == [300]
