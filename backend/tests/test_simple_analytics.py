"""Usage analytics: totals, per-project breakdown and UTC day buckets (D10)."""
from datetime import datetime, timezone

import pytest


def _ts(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def analytics(task_db_session_factory, monkeypatch):
    import simple_analytics
    from models.usage_record import UsageRecord

    monkeypatch.setattr(simple_analytics, "SessionLocal", task_db_session_factory)
    session = task_db_session_factory()
    session.add_all([
        UsageRecord(timestamp=_ts(2026, 10, 1, 23, 30), project="Alpha", client_id="a@x.com", comments_count=100, operation_type="file_upload"),
        UsageRecord(timestamp=_ts(2026, 10, 2, 0, 30), project="Alpha", client_id="a@x.com", comments_count=50, operation_type="url_extraction"),
        UsageRecord(timestamp=_ts(2026, 10, 2, 12, 0), project="Beta", client_id="b@x.com", comments_count=50, operation_type="file_upload"),
        UsageRecord(timestamp=_ts(2026, 8, 1), project="Old", client_id="b@x.com", comments_count=999, operation_type="file_upload"),
    ])
    session.commit()
    session.close()
    return simple_analytics.EnhancedAnalyticsService()


def test_totals_and_breakdown(analytics):
    stats = analytics.get_project_stats_filtered("2026-10-01", "2026-10-03")
    assert stats["total_comments_processed"] == 200
    assert stats["total_operations"] == 3
    assert stats["total_projects"] == 2
    alpha, beta = stats["project_breakdown"]
    assert (alpha["project"], alpha["total_comments"], alpha["percentage"]) == ("Alpha", 150, 75.0)
    assert (alpha["file_uploads"], alpha["url_extractions"], alpha["operations"]) == (1, 1, 2)
    assert (beta["project"], beta["total_comments"]) == ("Beta", 50)


def test_daily_buckets_are_utc(analytics):
    series = {d["date"]: d for d in analytics.get_project_stats_filtered("2026-10-01", "2026-10-03")["time_series_data"]}
    assert series["2026-10-01"]["comments"] == 100
    assert series["2026-10-02"]["comments"] == 100
    assert series["2026-10-02"]["operations"] == 2
    assert series["2026-10-03"]["comments"] == 0


def test_empty_range(analytics):
    stats = analytics.get_project_stats_filtered("2025-01-01", "2025-01-02")
    assert stats["total_operations"] == 0
    assert stats["project_breakdown"] == []
