"""A list of links is queued and processed one after another."""
import asyncio
import io

import openpyxl
import pandas as pd

from services import export_service
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
    urls = [f"https://x.com/{n}" for n in range(51)]
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


def test_hourly_link_budget(app_client, monkeypatch):
    monkeypatch.setattr(ExportCommentsService, "background_extract_and_cache_v2", _fake_extract([]))
    _login(app_client, "basic@example.com")
    for batch in range(2):
        urls = [f"https://x.com/{batch}/{n}" for n in range(50)]
        assert app_client.post("/api/process_url_queue/basic@example.com", json={"urls": urls, "project": "default"}).status_code == 200

    resp = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": ["https://x.com/more"], "project": "default"})
    assert resp.status_code == 429
    assert "0 left" in resp.json()["detail"]


def test_download_all_results_in_one_excel(app_client, monkeypatch, tmp_path):
    import services.analysis
    from utils.file_utils import create_excel_with_charts_enhanced
    monkeypatch.setattr(services.analysis, "UPLOAD_FOLDER", str(tmp_path))
    (tmp_path / "basic@example.com").mkdir()

    async def extract(self, task_id, client_id, payload, cache, manager, user_id=None, project=None):
        if "bad" in payload.url:
            return manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Extraction failed: private post")
        name = f"{payload.url[-1]}.xlsx"
        rows = pd.DataFrame({"Text": [f"comment on {name}"], "Translation": ["t"], "Sentiment Score": [0.9],
                             "Sentiment": ["positive"], "Category": ["Economy"]})
        objectives = [{"objective": "Trust", "relevant_comments": 1, "supports": 1, "neutral": 0, "against": 0,
                       "percent_met": 100, "average_alignment": 0.9, "summary": "ok"}]
        create_excel_with_charts_enhanced(rows, str(tmp_path / client_id / name), {}, {}, "", "", "", "", objectives)
        manager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "done", {"new_filename": name, "objective_results": objectives})

    monkeypatch.setattr(ExportCommentsService, "background_extract_and_cache_v2", extract)
    _login(app_client, "basic@example.com")
    urls = ["https://x.com/a", "https://x.com/bad", "https://x.com/c"]
    queue_id = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": urls, "project": "default"}).json()["queue_id"]

    resp = app_client.get(f"/api/queue_download/{queue_id}")
    assert resp.status_code == 200, resp.text
    book = pd.read_excel(io.BytesIO(resp.content), sheet_name=None)
    assert book["Links"]["Status"].tolist() == ["Done", "Failed", "Done"]
    assert "private post" in book["Links"]["Note"][1]
    assert book["All Comments"]["Source Link"].tolist() == ["https://x.com/a", "https://x.com/c"]
    assert book["All Comments"]["Sentiment"].tolist() == ["Aligned", "Aligned"]
    assert book["Objectives"]["Source Link"].tolist() == ["https://x.com/a", "https://x.com/c"]


def test_someone_elses_queue_cannot_be_downloaded(app_client, monkeypatch):
    monkeypatch.setattr(ExportCommentsService, "background_extract_and_cache_v2", _fake_extract([]))
    _login(app_client, "basic@example.com")
    queue_id = app_client.post("/api/process_url_queue/basic@example.com", json={"urls": ["https://x.com/a"], "project": "default"}).json()["queue_id"]
    _login(app_client, "admin@example.com")
    assert app_client.get(f"/api/queue_download/{queue_id}").status_code == 404


def test_links_read_from_an_excel_list(app_client):
    book = openpyxl.Workbook()
    book.active.append(["Post", "Notes"])
    book.active.append(["https://www.instagram.com/p/one/", "see https://www.instagram.com/p/two/ too"])
    book.active["A3"] = "Third post"
    book.active["A3"].hyperlink = "https://www.instagram.com/p/three/"
    book.active.append(["https://www.instagram.com/p/one/"])
    buffer = io.BytesIO()
    book.save(buffer)

    _login(app_client, "basic@example.com")
    resp = app_client.post("/api/link_list", files={"file": ("links.xlsx", buffer.getvalue())})
    assert resp.status_code == 200, resp.text
    assert resp.json()["links"] == ["https://www.instagram.com/p/one/", "https://www.instagram.com/p/two/", "https://www.instagram.com/p/three/"]

    assert app_client.post("/api/link_list", files={"file": ("links.xlsx", b"not excel")}).status_code == 400


def test_export_slots_are_shared(monkeypatch, tmp_path):
    monkeypatch.setattr(export_service, "EXPORTCOMMENTS_MAX_CONCURRENT", 1)
    monkeypatch.setattr(export_service, "EXPORT_SLOT_DIR", str(tmp_path))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda seconds: real_sleep(0))

    class Manager:
        messages = []
        def update_task_status(self, task_id, status, progress, message):
            self.messages.append((task_id, message))
        def is_task_cancelled(self, task_id):
            return False

    order = []

    async def job(name, hold):
        async with export_service.export_slot(name, Manager()):
            order.append(f"{name} start")
            for _ in range(hold):
                await real_sleep(0)
            order.append(f"{name} end")

    async def both():
        await asyncio.gather(job("a", 5), job("b", 0))

    asyncio.run(both())
    assert order == ["a start", "a end", "b start", "b end"]
    assert Manager.messages == [("b", "Waiting for other exports to finish...")]
