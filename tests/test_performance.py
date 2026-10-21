import asyncio
from time import perf_counter

import pytest

from ad_optimizer.analysis import Analyzer
from ad_optimizer.config import Settings
from ad_optimizer.models import Extraction, Translation
from ad_optimizer.providers import ServiceError, normalize


@pytest.mark.asyncio
async def test_bounded_parallel_batches_publish_incremental_results(monkeypatch):
    settings = Settings(_env_file=None, llm_concurrency=3)
    report = normalize([{"review_id": str(i), "rating": 3, "review_text": "Works at my office."} for i in range(20)], "B012345678", settings)
    active = peak = 0
    progress = []

    async def extract(self, batch):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.02)
            return Extraction(translations=[Translation(review_id=r.id, title_zh="", body_zh="在办公室使用。") for r in batch], issues=[], praises=[], neutral_feedback=[], topics=[])
        finally:
            active -= 1

    monkeypatch.setattr(Analyzer, "extract", extract)
    analyzer = Analyzer(settings)
    analyzer.on_progress = lambda done, total, processed: progress.append((done, total, processed, report.analyzed_count))
    await analyzer.analyze(report)
    assert peak == 3
    assert progress[0] == (0, 4, 0, 0)
    assert progress[-1] == (4, 4, 20, 20)
    assert progress[1][3] == 5
    assert report.analyzed_count == 20


@pytest.mark.asyncio
async def test_fatal_error_cancels_other_batches(monkeypatch):
    settings = Settings(_env_file=None, llm_concurrency=2)
    report = normalize([{"review_id": str(i), "rating": 1, "review_text": "Stopped working."} for i in range(10)], "B012345678", settings)
    active = 0
    calls = 0

    async def extract(self, batch):
        nonlocal active, calls
        calls += 1
        first = calls == 1
        active += 1
        try:
            if first:
                await asyncio.sleep(.01)
                raise ServiceError("LLM_AUTH_ERROR", "test auth failure")
            await asyncio.sleep(10)
        finally:
            active -= 1

    monkeypatch.setattr(Analyzer, "extract", extract)
    with pytest.raises(ServiceError) as error:
        await Analyzer(settings).analyze(report)
    assert error.value.code == "LLM_AUTH_ERROR"
    assert active == 0
