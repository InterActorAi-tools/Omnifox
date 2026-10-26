"""Project trends: per-upload stats, kept beyond result retention, visible only to members."""
from datetime import datetime, timedelta, timezone

from tests.test_private_projects import _create_private, _login


def _result(positive, negative, supports, relevant):
    return {
        "total_comments": positive + negative,
        "sentiment_counts": {"Positive": positive, "Negative": negative},
        "objective_results": [{"objective": "Win trust", "relevant_comments": relevant, "supports": supports,
                               "percent_met": round(100 * supports / relevant, 1), "summary": "secret text"}],
    }


def _upload(client, day, *counts):
    from models import ProjectSnapshot
    from services.trends import record_snapshot
    record_snapshot("Secret campaign", f"task-{day}", _result(*counts))
    with client.db() as db:
        snapshot = db.query(ProjectSnapshot).filter(ProjectSnapshot.task_id == f"task-{day}").one()
        snapshot.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=day)
        db.commit()


def test_trends_follow_each_upload(app_client):
    project = _create_private(app_client)
    _upload(app_client, 2, 6, 4, 3, 10)
    _upload(app_client, 1, 2, 8, 1, 10)

    trends = app_client.get(f"/api/projects/{project['id']}/trends").json()
    assert [u["positive_percent"] for u in trends["uploads"]] == [20.0, 60.0]  # oldest first
    assert [u["objectives"] for u in trends["uploads"]] == [[10.0], [30.0]]
    assert trends["objectives"] == [{"objective": "Win trust", "percent_met": 20.0, "latest": 30.0, "trend": "rising"}]
    assert trends["overall"] == {"uploads": 2, "comments": 20, "positive_percent": 40.0, "neutral_percent": 0.0,
                                 "negative_percent": 60.0, "sentiment_trend": "rising"}


def test_snapshots_hold_no_text_and_are_encrypted(app_client):
    _create_private(app_client)
    _upload(app_client, 1, 2, 8, 1, 10)
    from sqlalchemy import text
    with app_client.db() as db:
        stored = db.execute(text("SELECT stats FROM project_snapshots")).scalar()
    from utils.crypto import decrypt
    assert "Win trust" not in stored and "secret text" not in decrypt(stored.encode()).decode()


def test_one_upload_has_no_trend_yet(app_client):
    project = _create_private(app_client)
    _upload(app_client, 1, 2, 8, 1, 10)
    trends = app_client.get(f"/api/projects/{project['id']}/trends").json()
    assert trends["objectives"][0]["trend"] is None and trends["overall"]["sentiment_trend"] is None


def test_trends_of_a_private_project_are_hidden_from_others(app_client):
    project = _create_private(app_client)
    _login(app_client, "admin@example.com")
    assert app_client.get(f"/api/projects/{project['id']}/trends").status_code == 404


def test_deleting_the_project_deletes_its_snapshots(app_client):
    project = _create_private(app_client)
    _upload(app_client, 1, 2, 8, 1, 10)
    assert app_client.delete(f"/api/projects/{project['id']}").status_code == 200
    from models import ProjectSnapshot
    with app_client.db() as db:
        assert db.query(ProjectSnapshot).count() == 0
