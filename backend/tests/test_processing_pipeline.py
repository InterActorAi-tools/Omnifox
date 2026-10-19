"""Core pipeline: Excel in -> AI results -> Excel out, with Gemini faked (D15)."""
import io

import openpyxl
import pandas as pd
import pytest

from utils.crypto import is_encrypted, read_file, write_file


class FakeGemini:
    """Positive for most comments, negative for 'bad', no answer for 'fail'."""

    async def analyze_comments_batch_with_context(self, texts, post_context=None, progress_callback=None, objectives=()):
        results = []
        for text in texts:
            if "fail" in text:
                results.append(None)
            elif "bad" in text:
                results.append({"translation": f"EN {text}", "score": -0.7, "sentiment": "Negative", "category": "Other",
                                "objectives": [{"stance": "against", "alignment": 0.1} for _ in objectives]})
            else:
                results.append({"translation": f"EN {text}", "score": 0.8, "sentiment": "Positive", "category": "Other",
                                "objectives": [{"stance": "supports", "alignment": 0.9} for _ in objectives]})
        return results

    async def summarize_objectives(self, objectives, rows):
        return [f"summary of {o}" for o in objectives]

    async def summarize(self, rows, post_context="", request=""):
        return {"overall": "overall summary", "positive": "pos summary", "neutral": "neu summary", "negative": "neg summary"}


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    import services.processing as processing
    import simple_analytics

    monkeypatch.setattr(processing, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(simple_analytics.simple_analytics, "track_usage", lambda **kwargs: None)
    monkeypatch.setattr(processing, "project_objectives", lambda project: [])
    service = processing.ProcessingService()
    service.gemini_service = FakeGemini()

    client_dir = tmp_path / "alice@example.com"
    client_dir.mkdir()
    source = client_dir / "comments.xlsx"
    buffer = io.BytesIO()
    pd.DataFrame({"Text": [
        "great product",
        "bad service",
        "please fail here",
        '=HYPERLINK("http://evil.example","click")',
        "love it",
    ]}).to_excel(buffer, index=False, engine="xlsxwriter",
                 engine_kwargs={"options": {"strings_to_formulas": False}})
    write_file(str(source), buffer.getvalue())
    return service, source, client_dir


@pytest.mark.asyncio
async def test_pipeline_produces_counts_file_and_skips(pipeline):
    service, source, client_dir = pipeline

    result = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx")

    assert result["original_comments"] == 5
    assert result["total_comments"] == 4
    assert result["skipped_rows"] == 1  # surfaced to the user since D3
    assert result["sentiment_counts"] == {"positive": 3, "negative": 1}
    assert result["positive_context"] == "pos summary"
    assert result["overall_summary"] == "overall summary"
    assert "output_path" not in result

    output = client_dir / result["new_filename"]
    assert is_encrypted(output.read_bytes())  # never plaintext on disk
    sheet = openpyxl.load_workbook(io.BytesIO(read_file(str(output))))["Processed Data"]
    texts = [row[0].value for row in sheet.iter_rows(min_row=2)]
    assert "please fail here" not in texts
    # Untrusted comment text must stay a string, never a live formula.
    formula_cell = next(row[0] for row in sheet.iter_rows(min_row=2) if str(row[0].value).startswith("=HYPERLINK"))
    assert formula_cell.data_type == "s"


@pytest.mark.asyncio
async def test_output_names_do_not_collide(pipeline):
    service, source, _ = pipeline
    first = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx")
    second = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx")
    assert first["new_filename"] != second["new_filename"]


@pytest.mark.asyncio
async def test_cell_values_survive_the_round_trip(pipeline):
    """Links stay text, "NA"/"None"/"007" stay as written, and input columns
    named like output columns are kept (found by the data review)."""
    service, source, client_dir = pipeline
    buffer = io.BytesIO()
    pd.DataFrame({
        "Text": ["https://example.com/" + "x" * 2100, "None", "great product"],
        "Country": ["NA", "UK", "N/A"],
        "Code": ["007", "010", "1"],
        "Sentiment": ["their own label", "b", "c"],
    }).to_excel(buffer, index=False, engine="xlsxwriter",
                engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}})
    write_file(str(source), buffer.getvalue())

    result = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx")

    sheet = openpyxl.load_workbook(io.BytesIO(read_file(str(client_dir / result["new_filename"]))))["Processed Data"]
    header = [c.value for c in sheet[1]]
    rows = [dict(zip(header, (c.value for c in row))) for row in sheet.iter_rows(min_row=2, max_row=4)]
    assert result["original_comments"] == 3 and result["total_comments"] == 3
    assert [r["Text"] for r in rows][:2] == ["https://example.com/" + "x" * 2100, "None"]
    assert all(c.hyperlink is None for row in sheet.iter_rows(min_row=2, max_row=4) for c in row)
    assert [r["Country"] for r in rows] == ["NA", "UK", "N/A"]
    assert [r["Code"] for r in rows] == ["007", "010", "1"]
    assert [r["Sentiment (original)"] for r in rows] == ["their own label", "b", "c"]


@pytest.mark.asyncio
async def test_comments_are_scored_against_campaign_objectives(pipeline):
    service, source, client_dir = pipeline
    objectives = ["Raise awareness of the vaccine drive", "Build trust in the ministry"]

    result = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx",
                                                 objectives=objectives)

    first = result["objective_results"][0]
    assert first["objective"] == objectives[0]
    assert (first["relevant_comments"], first["supports"], first["against"]) == (4, 3, 1)
    assert first["percent_met"] == 75.0
    assert first["average_alignment"] == 0.7
    assert first["summary"] == f"summary of {objectives[0]}"

    workbook = openpyxl.load_workbook(io.BytesIO(read_file(str(client_dir / result["new_filename"]))))
    header = [c.value for c in workbook["Processed Data"][1]]
    assert {"Objective 1 Stance", "Objective 1 Alignment", "Objective 2 Stance", "Objective 2 Alignment"} <= set(header)
    assert [c.value for c in workbook["Objectives"][1]][:2] == ["Objective", "Relevant Comments"]
    assert workbook["Objectives"].cell(row=3, column=1).value == objectives[1]


@pytest.mark.asyncio
async def test_no_objectives_adds_nothing(pipeline):
    service, source, client_dir = pipeline
    result = await service.process_file_contents(str(source), "alice@example.com", "comments.xlsx")
    assert result["objective_results"] == []
    assert "Objectives" not in openpyxl.load_workbook(io.BytesIO(read_file(str(client_dir / result["new_filename"])))).sheetnames


def test_project_objectives_are_cleaned():
    from schemas.projects import ProjectCreate

    project = ProjectCreate(name="Q4", objectives=["Build trust\r", "", "  ", "Build trust", "Raise awareness"])
    assert project.objectives == ["Build trust", "Raise awareness"]
    with pytest.raises(ValueError):
        ProjectCreate(name="Q4", objectives=[f"objective {i}" for i in range(11)])
