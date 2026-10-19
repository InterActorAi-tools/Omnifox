"""Batched, schema-validated comment classification."""
import json

import pytest


def _service(answer):
    """GeminiService whose _generate answers each batch via answer(ids, call_no)."""
    from services.gemini_service import GeminiService
    service = GeminiService()
    calls = []

    async def fake_generate(contents, config, model=None):
        payload = contents[contents.index("<comments>\n") + 11:contents.rindex("\n</comments>")]
        ids = [c["id"] for c in json.loads(payload)]
        calls.append(ids)
        return answer(ids, len(calls))

    service._generate = fake_generate
    return service, calls


def _ok(ids, score=0.5, category="Economy"):
    return json.dumps([{"id": i, "translation": f"t{i}", "score": score, "category": category} for i in ids])


@pytest.mark.asyncio
async def test_comments_are_batched_and_duplicates_analysed_once():
    service, calls = _service(lambda ids, n: _ok(ids))
    texts = [f"comment {i}" for i in range(60)] + ["comment 0"]

    results = await service.analyze_comments_batch_with_context(texts)

    assert sorted(len(c) for c in calls) == [10, 25, 25]
    assert len(results) == 61 and results[0] == results[60]
    assert results[0] == {"translation": "t0", "score": 0.5, "sentiment": "Positive", "category": "Economy"}


@pytest.mark.asyncio
async def test_missing_and_invalid_answers_are_retried():
    def answer(ids, n):
        if n == 1:
            return "not json"
        if n == 2:
            return _ok(ids[:1])  # only the first comment answered
        return _ok(ids)
    service, calls = _service(answer)

    results = await service.analyze_comments_batch_with_context(["a", "b"])

    assert calls == [[0, 1], [0, 1], [1]]
    assert all(results)


@pytest.mark.asyncio
async def test_unanswered_comment_is_reported_as_none():
    service, _ = _service(lambda ids, n: _ok([i for i in ids if i != 1]))
    results = await service.analyze_comments_batch_with_context(["a", "b"])
    assert results[0] is not None and results[1] is None


@pytest.mark.asyncio
async def test_scores_are_clamped_labelled_and_categories_normalised():
    service, _ = _service(lambda ids, n: json.dumps(
        [{"id": ids[0], "translation": "x", "score": -7, "category": "not a category"}]))
    [result] = await service.analyze_comments_batch_with_context(["a"])
    assert result == {"translation": "x", "score": -1.0, "sentiment": "Negative", "category": "Other"}


@pytest.mark.asyncio
async def test_placeholder_translation_is_rejected():
    service, _ = _service(lambda ids, n: json.dumps(
        [{"id": ids[0], "translation": "Translation", "score": 0, "category": "Other"}]))
    assert await service.analyze_comments_batch_with_context(["a"]) == [None]


@pytest.mark.asyncio
async def test_real_request_path_with_fake_sdk_client():
    """Goes through _generate (rate limiting, executor, config) with only the SDK faked."""
    from types import SimpleNamespace
    from services.gemini_service import CLASSIFY_CONFIG, GeminiService
    sent = []

    def generate_content(model, contents, config):
        sent.append((model, config))
        payload = contents[contents.index("<comments>\n") + 11:contents.rindex("\n</comments>")]
        return SimpleNamespace(text=_ok([c["id"] for c in json.loads(payload)]))

    service = GeminiService()
    service.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    [result] = await service.analyze_comments_batch_with_context(["hello"])

    assert result["translation"] == "t0"
    assert sent == [(service.primary_model, CLASSIFY_CONFIG)]


@pytest.mark.asyncio
async def test_summaries_use_counts_categories_and_request():
    from types import SimpleNamespace
    from services.gemini_service import GeminiService
    sent = []

    def generate_content(model, contents, config):
        sent.append(contents)
        return SimpleNamespace(text=json.dumps({"overall": "O", "positive": "P", "neutral": "N", "negative": "X"}))

    service = GeminiService()
    service.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    rows = [{"translation": "Prices are too high", "sentiment": "negative", "category": "Economy"},
            {"translation": "Great work", "sentiment": "positive", "category": "Governance"}]

    summaries = await service.summarize(rows, post_context="Budget post", request="focus on prices")

    assert summaries == {"overall": "O", "positive": "P", "neutral": "No neutral comments.", "negative": "X"}
    prompt = sent[0]
    assert "<analyst_context>\nBudget post" in prompt and "<analyst_request>\nfocus on prices" in prompt
    assert '<comments sentiment="negative" count="1"' in prompt and "[Economy] Prices are too high" in prompt


@pytest.mark.asyncio
async def test_nan_scores_and_non_text_translations_are_rejected():
    service, _ = _service(lambda ids, n: '[{"id": 0, "translation": "x", "score": NaN, "category": "Other"},'
                                         ' {"id": 1, "translation": null, "score": 0.5, "category": "Other"}]')
    assert await service.analyze_comments_batch_with_context(["a", "b"]) == [None, None]


@pytest.mark.asyncio
async def test_summary_sample_spreads_over_large_skewed_groups():
    from types import SimpleNamespace
    from services.gemini_service import SUMMARY_CHAR_BUDGET, GeminiService
    sent = []

    def generate_content(model, contents, config):
        sent.append(contents)
        return SimpleNamespace(text=json.dumps({"overall": "O", "positive": "P", "neutral": "N", "negative": "X"}))

    service = GeminiService()
    service.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    rows = [{"translation": f"positive comment {i:05d} " + "y" * 900, "sentiment": "positive", "category": "Other"}
            for i in range(9990)]
    rows += [{"translation": f"negative comment {i} " + "z" * 900, "sentiment": "negative", "category": "Other"}
             for i in range(10)]

    await service.summarize(rows)

    prompt = sent[0]
    assert "positive comment 00000" in prompt and "positive comment 09" in prompt  # start and end of the group
    assert all(f"negative comment {i} " in prompt for i in range(10))           # small group fully seen
    assert len(prompt) < SUMMARY_CHAR_BUDGET * 1.15
