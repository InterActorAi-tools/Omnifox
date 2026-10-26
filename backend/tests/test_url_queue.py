"""A list of links is queued and processed one after another."""
from services.export_service import ExportCommentsService
from task_manager import TaskStatus
from tests.test_private_projects import _create_private, _login


def _fake_extract(order):
    async def extract(self, task_id, client_id, payload, cache, manager, user_id=None, project=None):
        order.append(payload.url)
        if "bad" in payload.url:
            manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Extraction failed: no comments found")
        else:
            manager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "done", {"new_filename": f"{len(order)}.xlsx"})
    return extract


def test_links_run_in_order_and_report_each_result(app_client, monkeypatch):
    order = []
    monkeypatch.setattr(ExportCommentsService, "background_extract_and_cache_v2", _fake_extract(order))
    _login(app_client, "basic@example.com")
    urls = ["https://x.com/a", "https://x.com/bad", " https://x.com/a ", "https://x.com/c"]

    resp = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": urls, "project": "default"})
    assert resp.status_code == 200, resp.text
    assert order == ["https://x.com/a", "https://x.com/bad", "https://x.com/c"]  # duplicates dropped

    queue = app_client.get("/api/tasks/me/queue").json()["queue"]
    assert queue["status"] == "completed"
    assert [(i["status"], i.get("filename")) for i in queue["items"]] == [("done", "1.xlsx"), ("failed", None), ("done", "3.xlsx")]
    assert "no comments" in queue["items"][1]["message"]


def test_too_many_links_refused(app_client):
    _login(app_client, "basic@example.com")
    urls = [f"https://x.com/{n}" for n in range(11)]
    resp = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": urls, "project": "default"})
    assert resp.status_code == 400


def test_queue_to_someone_elses_private_project_refused(app_client):
    _create_private(app_client)
    _login(app_client, "basic@example.com")
    resp = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": ["https://x.com/a"], "project": "Secret campaign"})
    assert resp.status_code == 404


def test_cancelling_the_queue_skips_the_remaining_links(app_client, monkeypatch):
    order = []
    extract = _fake_extract(order)

    async def extract_then_cancel(self, task_id, client_id, *args, **kwargs):
        from task_manager import task_manager
        queue = next(t for t in task_manager.get_client_tasks(client_id) if t.task_type == "url_queue")
        task_manager.cancel_task(queue.task_id)
        await extract(self, task_id, client_id, *args, **kwargs)

    monkeypatch.setattr(ExportCommentsService, "background_extract_and_cache_v2", extract_then_cancel)
    _login(app_client, "basic@example.com")
    app_client.post("/api/process_url_queue/basic@example.com", json={"urls": ["https://x.com/a", "https://x.com/b"], "project": "default"})

    queue = app_client.get("/api/tasks/me/queue").json()["queue"]
    assert order == ["https://x.com/a"]
    assert queue["status"] == "cancelled"
    assert [i["status"] for i in queue["items"]] == ["done", "cancelled"]
