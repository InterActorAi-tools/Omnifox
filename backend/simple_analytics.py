"""
Enhanced Simple analytics service for Omnifox - Track project usage with date filtering.
Data is stored in PostgreSQL (persisted across deployments).
"""
import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func

from database import SessionLocal
from models.usage_record import UsageRecord

logger = logging.getLogger(__name__)


def _utc(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Dates without a timezone (e.g. "2026-10-01") are UTC, not server-local."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class EnhancedAnalyticsService:
    """Analytics tracking backed by PostgreSQL for persistence across deployments."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_db(self):
        return SessionLocal()

    def _parse_date_range(self, start_date: Optional[str], end_date: Optional[str]) -> Tuple[float, float]:
        now = time.time()

        if not start_date and not end_date:
            return now - (30 * 24 * 3600), now

        try:
            if start_date:
                start_dt = _as_utc(datetime.fromisoformat(start_date.replace('Z', '+00:00')))
                start_timestamp = start_dt.timestamp()
            else:
                start_timestamp = 0.0

            if end_date:
                end_dt = _as_utc(datetime.fromisoformat(end_date.replace('Z', '+00:00')))
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                end_timestamp = end_dt.timestamp()
            else:
                end_timestamp = now

        except ValueError as e:
            logger.error(f"Error parsing dates: {e}")
            start_timestamp = now - (30 * 24 * 3600)
            end_timestamp = now

        return start_timestamp, end_timestamp

    def _range_filter(self, start_ts: float, end_ts: float):
        return (UsageRecord.timestamp >= start_ts, UsageRecord.timestamp <= end_ts)

    def _generate_time_series_data(self, records: List[Tuple[float, int, str]],
                                   start_timestamp: float, end_timestamp: float) -> List[Dict[str, Any]]:
        date_range_days = (end_timestamp - start_timestamp) / (24 * 3600)

        if date_range_days <= 31:
            bucket_size = 24 * 3600
            date_format = "%Y-%m-%d"
        else:
            bucket_size = 7 * 24 * 3600
            date_format = "%Y-W%U"

        time_buckets: Dict[str, Dict[str, Any]] = {}
        current_time = start_timestamp
        while current_time < end_timestamp:
            bucket_key = _utc(current_time).strftime(date_format)
            time_buckets[bucket_key] = {
                'date': bucket_key,
                'comments': 0,
                'operations': 0,
                'file_uploads': 0,
                'url_extractions': 0,
            }
            current_time += bucket_size

        for timestamp, comments_count, operation_type in records:
            bucket_key = _utc(timestamp).strftime(date_format)
            if bucket_key in time_buckets:
                time_buckets[bucket_key]['comments'] += comments_count
                time_buckets[bucket_key]['operations'] += 1
                if operation_type == 'file_upload':
                    time_buckets[bucket_key]['file_uploads'] += 1
                else:
                    time_buckets[bucket_key]['url_extractions'] += 1

        return list(time_buckets.values())

    # ------------------------------------------------------------------
    # Public API (unchanged interface)
    # ------------------------------------------------------------------

    def track_usage(self, project: str, client_id: str, comments_count: int, operation_type: str):
        """Persist a usage record to the database."""
        db = self._get_db()
        try:
            record = UsageRecord(
                timestamp=time.time(),
                project=project,
                client_id=client_id,
                comments_count=comments_count,
                operation_type=operation_type,
            )
            db.add(record)
            db.commit()
            logger.info(f"Tracked usage: {project} - {comments_count} comments ({operation_type})")
        except Exception as e:
            db.rollback()
            logger.error(f"Error tracking usage: {e}")
        finally:
            db.close()

    def get_project_stats_filtered(self, start_date: Optional[str] = None,
                                   end_date: Optional[str] = None) -> Dict[str, Any]:
        """Return project statistics for the given date range."""
        start_ts, end_ts = self._parse_date_range(start_date, end_date)

        in_range = self._range_filter(start_ts, end_ts)
        db = self._get_db()
        try:
            # Per-project totals in SQL instead of loading every row.
            is_upload = case((UsageRecord.operation_type == 'file_upload', 1), else_=0)
            rows = (
                db.query(
                    UsageRecord.project,
                    func.sum(UsageRecord.comments_count),
                    func.count(UsageRecord.id),
                    func.sum(is_upload),
                )
                .filter(*in_range)
                .group_by(UsageRecord.project)
                .all()
            )
            # The chart only needs three columns per record.
            records = (
                db.query(UsageRecord.timestamp, UsageRecord.comments_count, UsageRecord.operation_type)
                .filter(*in_range)
                .all()
            )
        finally:
            db.close()

        date_range = {
            'start_date': _utc(start_ts).isoformat(),
            'end_date': _utc(end_ts).isoformat(),
            'total_days': round((end_ts - start_ts) / (24 * 3600), 1),
        }

        if not rows:
            return {
                'total_comments_processed': 0,
                'total_operations': 0,
                'total_projects': 0,
                'project_breakdown': [],
                'date_range': date_range,
                'time_series_data': [],
            }

        project_totals = {
            project: {
                'total_comments': int(comments or 0),
                'operations': int(operations),
                'file_uploads': int(uploads or 0),
                'url_extractions': int(operations) - int(uploads or 0),
            }
            for project, comments, operations, uploads in rows
        }
        total_comments = sum(t['total_comments'] for t in project_totals.values())

        project_stats = []
        for project, stats in project_totals.items():
            percentage = (stats['total_comments'] / total_comments * 100) if total_comments > 0 else 0
            project_stats.append({
                'project': project,
                'total_comments': stats['total_comments'],
                'percentage': round(percentage, 1),
                'operations': stats['operations'],
                'file_uploads': stats['file_uploads'],
                'url_extractions': stats['url_extractions'],
            })

        project_stats.sort(key=lambda x: x['total_comments'], reverse=True)
        time_series_data = self._generate_time_series_data(records, start_ts, end_ts)

        return {
            'total_comments_processed': total_comments,
            'total_operations': len(records),
            'total_projects': len(project_totals),
            'project_breakdown': project_stats,
            'date_range': date_range,
            'time_series_data': time_series_data,
        }

    def get_quick_preset_stats(self, preset: str) -> Dict[str, Any]:
        """Return stats for common time presets."""
        now = datetime.now(timezone.utc)

        presets = {
            "last_7_days": (now - timedelta(days=7), now),
            "last_30_days": (now - timedelta(days=30), now),
            "last_60_days": (now - timedelta(days=60), now),
            "last_90_days": (now - timedelta(days=90), now),
            "this_month": (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now),
        }

        if preset == "last_month":
            last_month_end = now.replace(day=1) - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_date = last_month_start.isoformat()
            end_date = last_month_end.replace(hour=23, minute=59, second=59).isoformat()
        elif preset in presets:
            start_dt, end_dt = presets[preset]
            start_date = start_dt.isoformat()
            end_date = end_dt.isoformat()
        else:
            start_date = (now - timedelta(days=30)).isoformat()
            end_date = now.isoformat()

        return self.get_project_stats_filtered(start_date, end_date)

# Singleton instances (same names as before for backward compatibility)
enhanced_analytics = EnhancedAnalyticsService()
simple_analytics = enhanced_analytics