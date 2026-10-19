"""
Postgres-backed URL cache for Omnifox.

Caches ExportComments extractions (and their processed results) per
URL + project with a 24-hour TTL. Stored in the `url_cache` table so all
Gunicorn workers share one cache; the previous cache/url_cache.json file
was loaded into each worker's memory and drifted apart.

The public interface (CacheEntry, cache_service and its methods) is
unchanged, so routes and services need no changes.
"""
import time
import hashlib
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal
from models.url_cache import UrlCacheEntry

logger = logging.getLogger(__name__)

@dataclass
class CacheEntry:
    """Represents a cached URL extraction result"""
    url: str
    url_hash: str
    project: str
    extracted_filename: str
    processed_filename: Optional[str] = None
    comments_count: int = 0
    sentiment_data: Optional[Dict[str, Any]] = None
    created_at: float = 0
    last_accessed: float = 0
    is_processed: bool = False


def _row_to_entry(row: UrlCacheEntry) -> CacheEntry:
    return CacheEntry(
        url=row.url,
        url_hash=row.url_hash,
        project=row.project,
        extracted_filename=row.extracted_filename,
        processed_filename=row.processed_filename,
        comments_count=row.comments_count,
        sentiment_data=row.sentiment_data,
        created_at=row.created_at,
        last_accessed=row.last_accessed,
        is_processed=row.is_processed,
    )


class DatabaseCacheService:
    """Database-backed cache service for URL extractions only"""

    def __init__(self, ttl_hours: int = 24, max_entries: int = 100):
        self.ttl_hours = ttl_hours
        self.max_entries = max_entries

    def _generate_url_hash(self, url: str, project: str, client_id: str) -> str:
        """Cache key: one entry per user, URL and project."""
        combined = f"{client_id}:{url}:{project}"
        return hashlib.sha256(combined.encode()).hexdigest()

    def _expiry_cutoff(self) -> float:
        return time.time() - self.ttl_hours * 3600

    def get_cached_url(self, url: str, project: str, client_id: str) -> Optional[CacheEntry]:
        """Get the user's cached URL data if available and not expired"""
        url_hash = self._generate_url_hash(url, project, client_id)
        session = SessionLocal()
        try:
            row = session.get(UrlCacheEntry, url_hash)
            if row is None:
                return None

            if row.created_at < self._expiry_cutoff():
                self._delete_rows(session, [row])
                return None

            row.last_accessed = time.time()
            session.commit()

            logger.info(f"Cache hit: {url_hash[:8]}")
            return _row_to_entry(row)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Cache lookup failed: {exc}")
            return None
        finally:
            session.close()

    def get_cached_url_validated(
        self, url: str, project: str, client_id: str
    ) -> Optional[CacheEntry]:
        """Like get_cached_url but verifies that the recorded files are
        actually on disk for the given client. If the cache claims a file
        that no longer exists, the stale entry is evicted and None is
        returned so the caller can fall through to a fresh extraction.

        Background: the cache stores bare filenames and the files live
        under UPLOAD_FOLDER/<client_id>/. Volume wipes, redeploys with a
        fresh bind mount, or manual cleanups can leave the cache pointing
        at files that no longer exist. Returning a stale path makes the
        next /api/download/... call 404. Validating up-front turns that
        into a transparent re-extraction.
        """
        entry = self.get_cached_url(url, project, client_id)
        if entry is None:
            return None

        from config import UPLOAD_FOLDER

        client_dir = Path(UPLOAD_FOLDER) / client_id

        # Determine which filename(s) the caller will actually try to use.
        # The route returns processed_filename when is_processed is True,
        # otherwise it re-processes from extracted_filename.
        required: list[str] = []
        if entry.is_processed and entry.processed_filename:
            required.append(entry.processed_filename)
        elif entry.extracted_filename:
            required.append(entry.extracted_filename)

        missing = [
            fname for fname in required
            if not (client_dir / fname).exists()
        ]
        if missing:
            logger.warning(
                "cache_service: evicting stale entry %s - files missing on disk: %s",
                entry.url_hash[:8], missing,
            )
            session = SessionLocal()
            try:
                session.query(UrlCacheEntry).filter(UrlCacheEntry.url_hash == entry.url_hash).delete()
                session.commit()
            except SQLAlchemyError as exc:
                session.rollback()
                logger.error(f"Cache eviction failed: {exc}")
            finally:
                session.close()
            return None

        return entry

    def cache_url_extraction(self, url: str, project: str, client_id: str, comments_count: int,
                           extracted_filename: str) -> str:
        """Cache URL extraction result (best effort: errors are logged)"""
        url_hash = self._generate_url_hash(url, project, client_id)
        now = time.time()
        session = SessionLocal()
        try:
            session.merge(UrlCacheEntry(
                url_hash=url_hash,
                client_id=client_id,
                url=url,
                project=project,
                extracted_filename=extracted_filename,
                processed_filename=None,
                comments_count=comments_count,
                sentiment_data=None,
                is_processed=False,
                created_at=now,
                last_accessed=now,
            ))
            session.commit()
            self._enforce_max_entries(session)
            logger.info(f"Cached URL extraction: {url_hash[:8]}")
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to cache URL extraction: {exc}")
        finally:
            session.close()
        return url_hash

    def cache_url_processing(self, url_hash: str, processed_filename: str,
                           sentiment_data: Dict[str, Any]):
        """Cache URL processing result (best effort: errors are logged)"""
        session = SessionLocal()
        try:
            row = session.get(UrlCacheEntry, url_hash)
            if row is None:
                return
            row.processed_filename = processed_filename
            row.sentiment_data = sentiment_data
            row.is_processed = True
            row.last_accessed = time.time()
            session.commit()
            logger.info(f"Cached URL processing: {url_hash[:8]}")
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Failed to cache URL processing: {exc}")
        finally:
            session.close()

    def _delete_rows(self, session, rows: List[UrlCacheEntry]) -> None:
        """Delete cache rows (expiry / LRU eviction). Result files stay until
        the 30-day retention job removes them (services/privacy.py)."""
        for row in rows:
            session.delete(row)
        session.commit()

    def cleanup_expired(self) -> int:
        """Clean up expired cache entries"""
        session = SessionLocal()
        try:
            expired = session.query(UrlCacheEntry).filter(
                UrlCacheEntry.created_at < self._expiry_cutoff()
            ).all()
            if expired:
                self._delete_rows(session, expired)
                logger.info(f"Cleaned up {len(expired)} expired cache entries")
            return len(expired)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(f"Cache cleanup failed: {exc}")
            return 0
        finally:
            session.close()

    def _enforce_max_entries(self, session):
        """Enforce maximum number of cache entries (LRU eviction)"""
        total = session.query(func.count(UrlCacheEntry.url_hash)).scalar() or 0
        if total <= self.max_entries:
            return

        entries_to_remove = total - self.max_entries
        oldest = (
            session.query(UrlCacheEntry)
            .order_by(UrlCacheEntry.last_accessed.asc())
            .limit(entries_to_remove)
            .all()
        )
        self._delete_rows(session, oldest)
        logger.info(f"Evicted {entries_to_remove} entries to enforce max limit")

# Global cache service instance
cache_service = DatabaseCacheService()
