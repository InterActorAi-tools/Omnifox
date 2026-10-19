"""The ExportComments SDK is synchronous; it must not block the event loop (D1)."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_export_job_creation_does_not_block_event_loop():
    from services.export_service import ExportCommentsService

    service = ExportCommentsService.__new__(ExportCommentsService)

    def slow_create(**_kwargs):
        time.sleep(0.5)  # a slow, blocking HTTP call inside the SDK
        raise RuntimeError("upstream unavailable")

    service.export_client = SimpleNamespace(jobs=SimpleNamespace(create=slow_create))
    task_manager = MagicMock()
    task_manager.is_task_cancelled.return_value = False

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    payload = SimpleNamespace(url="https://youtube.com/watch?v=x", project="p", post_context="")
    await service.background_extract_and_cache_v2("t1", "a@x.com", payload, MagicMock(), task_manager)
    ticker_task.cancel()

    # Blocking call on the loop -> 0 ticks; in a thread -> ~10 ticks.
    assert ticks >= 5
    task_manager.update_task_status.assert_called()
    assert "Failed to create export job" in task_manager.update_task_status.call_args[0][3]
