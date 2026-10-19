"""Tests for cache_service.get_cached_url_validated.

Regression test for the stale-cache 404 bug: when the cache claims a
processed file but the file no longer exists on disk (volume wipe,
redeploy, manual cleanup), the route used to return the dead filename
and the next /api/download/... call would 404. The validated variant
evicts and returns None so the caller falls through to a fresh
extraction.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def cache_with_upload_dir(tmp_path: Path, monkeypatch, task_db_session_factory):
    """Construct an isolated CacheService on the in-memory test DB and
    patch UPLOAD_FOLDER so the validation reads from a temp directory we
    control."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()

    # Patch the module-level UPLOAD_FOLDER lookup inside cache_service.
    # cache_service does `from config import UPLOAD_FOLDER` inside the
    # method, so we monkeypatch the source rather than the import alias.
    import config
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(uploads))

    from cache_service import DatabaseCacheService
    svc = DatabaseCacheService(ttl_hours=24, max_entries=10)

    return svc, uploads


def _entry_count():
    import cache_service
    from models.url_cache import UrlCacheEntry
    with cache_service.SessionLocal() as session:
        return session.query(UrlCacheEntry).count()


def _seed_processed_entry(svc, *, url="https://x.test/v", project="default"):
    """Insert a fully-processed cache entry, return the entry."""
    url_hash = svc.cache_url_extraction(url, project, "alice@example.com", 123, "extracted.xlsx")
    svc.cache_url_processing(url_hash, "processed.xlsx", {"sentiment": "neutral"})
    return svc.get_cached_url(url, project, "alice@example.com")


class TestGetCachedUrlValidated:
    def test_returns_entry_when_processed_file_exists(self, cache_with_upload_dir):
        svc, uploads = cache_with_upload_dir
        _seed_processed_entry(svc)

        client_dir = uploads / "alice@example.com"
        client_dir.mkdir()
        (client_dir / "processed.xlsx").write_text("real file")

        entry = svc.get_cached_url_validated(
            "https://x.test/v", "default", "alice@example.com"
        )
        assert entry is not None
        assert entry.processed_filename == "processed.xlsx"

    def test_evicts_when_processed_file_missing(self, cache_with_upload_dir):
        svc, uploads = cache_with_upload_dir
        _seed_processed_entry(svc)

        client_dir = uploads / "alice@example.com"
        client_dir.mkdir()
        # NOTE: processed.xlsx intentionally NOT written - simulates the
        # 404 bug.

        result = svc.get_cached_url_validated(
            "https://x.test/v", "default", "alice@example.com"
        )
        assert result is None
        # Entry was evicted so a follow-up lookup also returns None.
        assert svc.get_cached_url("https://x.test/v", "default", "alice@example.com") is None

    def test_evicts_when_client_dir_does_not_exist(self, cache_with_upload_dir):
        svc, _ = cache_with_upload_dir
        _seed_processed_entry(svc)

        # No client directory has been created at all (new user).
        result = svc.get_cached_url_validated(
            "https://x.test/v", "default", "bob@example.com"
        )
        assert result is None

    def test_returns_entry_for_unprocessed_when_extracted_file_exists(
        self, cache_with_upload_dir
    ):
        svc, uploads = cache_with_upload_dir
        # Only cache extraction, not processing - so is_processed=False.
        svc.cache_url_extraction("https://x.test/v", "default", "alice@example.com", 5, "extracted.xlsx")

        client_dir = uploads / "alice@example.com"
        client_dir.mkdir()
        (client_dir / "extracted.xlsx").write_text("real file")

        entry = svc.get_cached_url_validated(
            "https://x.test/v", "default", "alice@example.com"
        )
        assert entry is not None
        assert entry.is_processed is False
        assert entry.extracted_filename == "extracted.xlsx"

    def test_evicts_when_extracted_file_missing(self, cache_with_upload_dir):
        svc, uploads = cache_with_upload_dir
        svc.cache_url_extraction("https://x.test/v", "default", "alice@example.com", 5, "extracted.xlsx")

        client_dir = uploads / "alice@example.com"
        client_dir.mkdir()
        # extracted.xlsx not written.

        result = svc.get_cached_url_validated(
            "https://x.test/v", "default", "alice@example.com"
        )
        assert result is None

    def test_returns_none_when_url_was_never_cached(self, cache_with_upload_dir):
        svc, _ = cache_with_upload_dir
        result = svc.get_cached_url_validated(
            "https://never-seen.test/", "default", "alice@example.com"
        )
        assert result is None

    def test_per_client_validation_isolated(self, cache_with_upload_dir):
        """Cache entries are shared across clients, but validation must
        check the CALLER's
        client_id, not just any client where the file happens to exist.

        Otherwise Bob asking about a URL whose file lives in Alice's
        directory would pass validation but then /api/download/bob/X
        would 404 anyway."""
        svc, uploads = cache_with_upload_dir
        _seed_processed_entry(svc)

        alice_dir = uploads / "alice@example.com"
        alice_dir.mkdir()
        (alice_dir / "processed.xlsx").write_text("real file")
        # Bob has no directory and no file.

        bob_result = svc.get_cached_url_validated(
            "https://x.test/v", "default", "bob@example.com"
        )
        assert bob_result is None


class TestPerUserCache:
    def test_other_users_never_get_an_entry(self, cache_with_upload_dir):
        svc, uploads = cache_with_upload_dir
        _seed_processed_entry(svc)
        (uploads / "bob@example.com").mkdir()
        (uploads / "bob@example.com" / "processed.xlsx").write_text("bob's own file")

        assert svc.get_cached_url("https://x.test/v", "default", "bob@example.com") is None
        assert svc.get_cached_url_validated("https://x.test/v", "default", "bob@example.com") is None


class TestSharedCacheBehaviour:
    def test_eviction_for_other_client_keeps_owners_files(self, cache_with_upload_dir):
        # Bob missing the file must not delete Alice's copy.
        svc, uploads = cache_with_upload_dir
        _seed_processed_entry(svc)
        alice_file = uploads / "alice@example.com" / "processed.xlsx"
        alice_file.parent.mkdir()
        alice_file.write_text("real file")

        assert svc.get_cached_url_validated("https://x.test/v", "default", "bob@example.com") is None
        assert alice_file.exists()

    def test_entries_are_shared_across_service_instances(self, cache_with_upload_dir):
        # Simulates two Gunicorn workers: a write from one is visible to the other.
        from cache_service import DatabaseCacheService
        svc, _ = cache_with_upload_dir
        _seed_processed_entry(svc)

        other_worker = DatabaseCacheService()
        entry = other_worker.get_cached_url("https://x.test/v", "default", "alice@example.com")
        assert entry is not None and entry.processed_filename == "processed.xlsx"

    def test_expired_entry_is_removed(self, cache_with_upload_dir):
        svc, _ = cache_with_upload_dir
        _seed_processed_entry(svc)
        svc.ttl_hours = 0

        assert svc.cleanup_expired() == 1
        assert _entry_count() == 0

    def test_lru_eviction_respects_max_entries(self, cache_with_upload_dir):
        svc, _ = cache_with_upload_dir
        svc.max_entries = 2
        for i in range(3):
            svc.cache_url_extraction(f"https://x.test/{i}", "default", "alice@example.com", 1, f"e{i}.xlsx")

        assert _entry_count() == 2
        assert svc.get_cached_url("https://x.test/0", "default", "alice@example.com") is None
