"""Chat about an analysis: memory, tools, proposals and access rules."""
from types import SimpleNamespace

import pandas as pd
import pytest
from google.genai import types

APP_PASSWORD = "Goodpass-12345"  # matches conftest
EMAIL = "basic@example.com"
FILE = "processed_result.xlsx"


class FakeGemini:
    """Plays back scripted responses: a str is a text answer, a tuple (name, args) a tool call."""
    script: list = []
    calls: list = []

    async def request(self, contents, config):
        FakeGemini.calls.append(list(contents))
        step = FakeGemini.script.pop(0)
        if isinstance(step, str):
            return SimpleNamespace(function_calls=None, text=step)
        call = types.FunctionCall(name=step[0], args=step[1])
        return SimpleNamespace(function_calls=[call], text=None, candidates=[
            SimpleNamespace(content=types.Content(role="model", parts=[types.Part(function_call=call)]))])

    async def summarize(self, rows, post_context="", request=""):
        return {"overall": f"new overall ({request})", "positive": "new pos", "neutral": "new neu", "negative": "new neg"}


@pytest.fixture
def client(app_client, tmp_path, monkeypatch):
    import routers.analysis
    import services.analysis
    import services.privacy
    from models import Task
    from utils.file_utils import create_excel_with_charts_enhanced

    for module in (routers.analysis, services.analysis, services.privacy):
        monkeypatch.setattr(module, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(routers.analysis, "get_gemini", FakeGemini)
    FakeGemini.script, FakeGemini.calls = [], []

    (tmp_path / EMAIL).mkdir()
    rows = pd.DataFrame({"Text": ["prix trop chers", "super travail"], "Translation": ["prices too high", "great work"],
                         "Sentiment Score": [-0.8, 0.9], "Sentiment": ["negative", "positive"],
                         "Category": ["Economy", "Governance"], "Likes": [3, 1]})
    create_excel_with_charts_enhanced(rows, str(tmp_path / EMAIL / FILE), {}, {}, "old pos", "old neu", "old neg", "old overall")
    with app_client.db() as db:
        db.add(Task(task_id="t1", client_id=EMAIL, status="completed", metadata_json={"post_context": "Budget post"},
                    result_data={"new_filename": FILE, "positive_context": "old pos", "overall_summary": "old overall"}))
        db.commit()
    resp = app_client.post("/api/auth/login", json={"email": EMAIL, "password": APP_PASSWORD})
    assert resp.status_code == 200
    app_client.headers["X-CSRF-Token"] = app_client.cookies.get("XSRF-TOKEN")
    return app_client


def test_chat_remembers_the_conversation(client):
    FakeGemini.script = ["Mostly about prices.", "The negative one mentions prices."]
    assert client.post(f"/api/analysis/{FILE}/chat", json={"message": "What is it about?"}).json()["reply"] == "Mostly about prices."
    client.post(f"/api/analysis/{FILE}/chat", json={"message": "Which is negative?"})

    second_call = FakeGemini.calls[1]
    assert [c.role for c in second_call] == ["user", "model", "user"]
    assert second_call[1].parts[0].text == "Mostly about prices."
    history = client.get(f"/api/analysis/{FILE}/chat").json()
    assert [(m["role"], m["text"]) for m in history][-1] == ("model", "The negative one mentions prices.")


def test_search_tool_returns_matching_comments(client):
    FakeGemini.script = [("search_comments", {"sentiment": "negative"}), "One negative comment."]
    client.post(f"/api/analysis/{FILE}/chat", json={"message": "Show negatives"})

    tool_result = FakeGemini.calls[1][-1].parts[0].function_response.response
    assert tool_result["total_matches"] == 1 and "prices too high" in tool_result["comments"][0]


def test_summary_proposal_is_applied_only_on_request(client):
    from services.analysis import Analysis
    FakeGemini.script = [("propose_summary_update", {"request": "focus on prices"}), "Here are new summaries."]
    proposal = client.post(f"/api/analysis/{FILE}/chat", json={"message": "Focus on prices"}).json()["proposals"][0]
    assert proposal["summaries"]["overall"] == "new overall (focus on prices)" and proposal["status"] == "pending"

    with client.db() as db:
        assert Analysis(db, EMAIL, FILE).summaries["overall"] == "old overall"  # nothing changed yet
    result = client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply").json()
    assert result["overall_summary"] == "new overall (focus on prices)"
    with client.db() as db:
        analysis = Analysis(db, EMAIL, FILE)
        assert analysis.summaries["overall"] == "new overall (focus on prices)"
        assert list(analysis.rows.columns) == ["Text", "Translation", "Sentiment Score", "Sentiment", "Category", "Likes"]
        assert len(analysis.rows) == 2
    assert client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply").status_code == 404


def test_dismissed_proposal_cannot_be_applied(client):
    FakeGemini.script = [("propose_summary_update", {"request": "shorter"}), "Done."]
    proposal = client.post(f"/api/analysis/{FILE}/chat", json={"message": "Shorter"}).json()["proposals"][0]
    assert client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/dismiss").status_code == 200
    assert client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply").status_code == 404


def test_other_users_cannot_reach_the_analysis(client):
    FakeGemini.script = [("propose_summary_update", {"request": "x"}), "Done."]
    proposal = client.post(f"/api/analysis/{FILE}/chat", json={"message": "x"}).json()["proposals"][0]

    client.post("/api/auth/login", json={"email": "dash@example.com", "password": APP_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("XSRF-TOKEN")
    assert client.post(f"/api/analysis/{FILE}/chat", json={"message": "hi"}).status_code == 404
    assert client.get(f"/api/analysis/{FILE}/chat").json() == []
    assert client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply").status_code == 404


def test_deleting_the_result_deletes_its_chat(client):
    FakeGemini.script = ["Hi."]
    client.post(f"/api/analysis/{FILE}/chat", json={"message": "hi"})
    assert client.delete(f"/api/users/me/results/{FILE}").status_code == 200
    assert client.get(f"/api/analysis/{FILE}/chat").json() == []


def test_relabel_proposal_keeps_only_valid_real_changes(client):
    FakeGemini.script = [("propose_relabel", {"reason": "sarcasm", "changes": [
        {"id": 1, "sentiment": "negative"},          # real change
        {"id": 0, "sentiment": "negative"},          # already negative: dropped
        {"id": 99, "sentiment": "positive"},         # no such comment: dropped
    ]}), "I marked the sarcastic one."]
    [proposal] = client.post(f"/api/analysis/{FILE}/chat", json={"message": "great work is sarcastic"}).json()["proposals"]

    assert proposal["type"] == "relabel" and proposal["reason"] == "sarcasm"
    assert proposal["changes"] == [{"id": 1, "translation": "great work",
                                    "from": {"sentiment": "positive", "category": "Governance"},
                                    "to": {"sentiment": "negative", "category": "Governance"}}]


def test_applying_relabels_updates_report_counts_and_summaries(client):
    from services.analysis import Analysis
    FakeGemini.script = [("propose_relabel", {"reason": "about prices", "changes": [
        {"id": 1, "sentiment": "negative", "category": "Economy"}]}), "Done."]
    proposal = client.post(f"/api/analysis/{FILE}/chat", json={"message": "fix it"}).json()["proposals"][0]

    result = client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply").json()

    assert result["sentiment_counts"] == {"negative": 2}
    assert result["category_counts"] == {"Economy": 2}
    assert result["overall_summary"] == "new overall ()"  # regenerated from the corrected labels
    with client.db() as db:
        rows = Analysis(db, EMAIL, FILE).rows
        assert rows.at[1, "Sentiment"] == "negative" and rows.at[1, "Sentiment Score"] == -0.5
        assert rows.at[1, "Likes"] == 1  # other columns untouched


def test_my_results_lists_existing_results_newest_first(client, tmp_path):
    from datetime import datetime, timedelta, timezone
    from models import Task
    from utils.crypto import write_file
    write_file(str(tmp_path / EMAIL / "newer.xlsx"), b"x")
    with client.db() as db:
        later = datetime.now(timezone.utc) + timedelta(minutes=1)
        db.add_all([
            Task(task_id="t2", client_id=EMAIL, status="completed", created_at=later,
                 metadata_json={"filename": "comments.xlsx", "project": "Alpha"},
                 result_data={"new_filename": "newer.xlsx", "total_comments": 5}),
            Task(task_id="t3", client_id=EMAIL, status="completed", result_data={"new_filename": "gone.xlsx"}),
            Task(task_id="t4", client_id=EMAIL, status="failed", result_data={"new_filename": FILE}),
        ])
        db.commit()

    results = client.get("/api/analysis").json()

    assert [r["filename"] for r in results] == ["newer.xlsx", FILE]  # missing file and failed task skipped
    assert results[0]["source"] == "comments.xlsx" and results[0]["project"] == "Alpha"


def test_opening_a_result_returns_counts_and_summaries(client):
    result = client.get(f"/api/analysis/{FILE}").json()
    assert result["sentiment_counts"] == {"negative": 1, "positive": 1}
    assert result["total_comments"] == 2 and result["overall_summary"] == "old overall"


def test_other_users_do_not_see_my_results(client):
    client.post("/api/auth/login", json={"email": "dash@example.com", "password": APP_PASSWORD})
    assert client.get("/api/analysis").json() == []
    assert client.get(f"/api/analysis/{FILE}").status_code == 404


def test_rewriting_keeps_every_column_and_the_file_age(client, tmp_path):
    import os
    from services.analysis import Analysis
    from utils.file_utils import create_excel_with_charts_enhanced
    path = tmp_path / EMAIL / "blank_header.xlsx"
    # An upload with a blank column header keeps it as "Unnamed: 5" metadata.
    rows = pd.DataFrame({"Text": ["a"], "Translation": ["a"], "Sentiment Score": [0.5], "Sentiment": ["positive"],
                         "Category": ["Other"], "Unnamed: 5": ["kept"], "Author": ["Sam"]})
    create_excel_with_charts_enhanced(rows, str(path), {}, {}, "", "", "", "")
    os.utime(path, (1_000_000, 1_000_000))

    with client.db() as db:
        Analysis(db, EMAIL, "blank_header.xlsx").save()
        again = Analysis(db, EMAIL, "blank_header.xlsx").rows

    assert list(again.columns) == list(rows.columns) and again.at[0, "Author"] == "Sam"
    assert os.path.getmtime(path) == 1_000_000


@pytest.mark.parametrize("args", [
    {"changes": ["not a dict", 5, None], "reason": "x"},
    {"changes": "everything", "reason": "x"},
    {"changes": [{"id": "lots", "sentiment": "negative"}]},
])
def test_malformed_tool_arguments_never_break_the_chat(client, args):
    FakeGemini.script = [("propose_relabel", args), ("search_comments", {"limit": "many"}), "Still here."]
    resp = client.post(f"/api/analysis/{FILE}/chat", json={"message": "x"})
    assert resp.status_code == 200 and resp.json()["reply"] == "Still here."
    assert resp.json()["proposals"] == []


def test_apply_locks_do_not_pile_up(client):
    import routers.analysis
    for i in range(5):
        client.post(f"/api/analysis/missing{i}.xlsx/proposals/1/apply")
    FakeGemini.script = [("propose_summary_update", {"request": "x"}), "Done."]
    proposal = client.post(f"/api/analysis/{FILE}/chat", json={"message": "x"}).json()["proposals"][0]
    client.post(f"/api/analysis/{FILE}/proposals/{proposal['id']}/apply")
    assert routers.analysis._apply_locks == {}



def test_a_column_named_NA_is_kept_when_the_report_is_rewritten(client, tmp_path):
    from services.analysis import Analysis
    from utils.file_utils import create_excel_with_charts_enhanced
    rows = pd.DataFrame({"Text": ["a"], "Translation": ["a"], "Sentiment Score": [0.5], "Sentiment": ["positive"],
                         "Category": ["Other"], "NA": ["x"], "Likes": [3]})
    create_excel_with_charts_enhanced(rows, str(tmp_path / EMAIL / "na.xlsx"), {}, {}, "", "", "", "")
    with client.db() as db:
        Analysis(db, EMAIL, "na.xlsx").save()
        assert list(Analysis(db, EMAIL, "na.xlsx").rows.columns) == list(rows.columns)


@pytest.mark.asyncio
async def test_apply_lock_serialises_a_third_request_arriving_late():
    """A releases while B still waits; C arriving then must wait for B."""
    import asyncio
    import routers.analysis as ra
    running, peak = 0, 0

    async def apply(name, delay=0.0):
        nonlocal running, peak
        await asyncio.sleep(delay)
        async with ra._result_lock("k"):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.1)
            running -= 1

    await asyncio.gather(apply("A"), apply("B", 0.01), apply("C", 0.15))
    assert peak == 1 and ra._apply_locks == {}
