import logging

import pytest

from ad_optimizer.analysis import Analyzer
from ad_optimizer.config import Settings
from ad_optimizer.models import Evidence, Extraction, Finding, Review, Translation
from ad_optimizer.providers import ServiceError, normalize


def sample_review():
    return Review(id="R-0", requested_asin="B012345678", rating=3,
                  body_original="It works at my office, but the lid is hard to clean.")


def output_for(reviews):
    return Extraction(translations=[Translation(review_id=r.id, title_zh="", body_zh="在办公室可用，但盖子难清洁。") for r in reviews],
                      issues=[], praises=[], neutral_feedback=[], topics=[])


@pytest.mark.asyncio
async def test_optional_insight_missing_description_gets_targeted_repair(monkeypatch, caplog):
    review = sample_review()
    valid = output_for([review]).model_dump()
    valid["usage_insights"] = [Finding(name="办公室", description="买家在办公室使用。", evidence=[Evidence(review_id=review.id, quote="It works at my office")]).model_dump()]
    invalid = {**valid, "usage_insights": [{"name": "办公室", "evidence": valid["usage_insights"][0]["evidence"]}]}
    prompts = []

    async def json_call(self, system, user):
        prompts.append(system)
        return invalid if len(prompts) == 1 else valid

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(Analyzer, "json_call", json_call)
    monkeypatch.setattr("ad_optimizer.analysis.asyncio.sleep", no_sleep)
    with caplog.at_level(logging.WARNING):
        result = await Analyzer(Settings(_env_file=None)).extract([review])
    assert result.usage_insights[0].description
    assert "usage_insights.0.description" in prompts[1]
    assert '"required"' in prompts[0]
    assert review.body_original not in caplog.text


@pytest.mark.asyncio
async def test_many_short_reviews_do_not_form_one_oversized_output(monkeypatch):
    settings = Settings(_env_file=None)
    rows = [{"review_id": str(i), "rating": 3, "review_text": "Works."} for i in range(12)]
    report = normalize(rows, "B012345678", settings)
    sizes = []

    async def extract(self, batch):
        sizes.append(len(batch))
        return output_for(batch)

    monkeypatch.setattr(Analyzer, "extract", extract)
    await Analyzer(settings).analyze(report)
    assert sizes == [5, 5, 2]
    assert report.analyzed_count == 12


@pytest.mark.asyncio
async def test_all_failed_batches_expose_actual_reason(monkeypatch):
    report = normalize([{"rating": 1, "review_text": "Stopped working."}], "B012345678", Settings(_env_file=None))

    async def extract(self, batch):
        raise ServiceError("LLM_OUTPUT_TRUNCATED", "模型输出被截断。")

    monkeypatch.setattr(Analyzer, "extract", extract)
    with pytest.raises(ServiceError) as error:
        await Analyzer(Settings(_env_file=None)).analyze(report)
    assert error.value.code == "LLM_OUTPUT_TRUNCATED"
    assert "截断" in error.value.message
    assert report.analyzed_count == 0


def test_bad_optional_insight_does_not_discard_valid_feedback():
    review = sample_review()
    output = output_for([review]).model_dump()
    output["neutral_feedback"] = [Finding(name="清洁", description="盖子难清洁。", evidence=[Evidence(review_id=review.id, quote="the lid is hard to clean")]).model_dump()]
    output["usage_insights"] = [{"name": "办公室", "evidence": [{"review_id": review.id, "quote": "It works at my office"}]}]
    analyzer = Analyzer(Settings(_env_file=None))
    recovered = analyzer.recover(output, [review])
    assert recovered is not None
    assert len(recovered.translations) == 1
    assert len(recovered.neutral_feedback) == 1
    assert recovered.usage_insights == []
    assert analyzer.recovery_warnings


def test_recovery_still_rejects_fabricated_quotes_and_wrong_star():
    review = sample_review()
    output = output_for([review]).model_dump()
    output["issues"] = [Finding(name="错误低星", description="不能使用3星", evidence=[Evidence(review_id=review.id, quote="the lid is hard to clean")]).model_dump()]
    output["topics"] = [{"name": "伪造", "evidence": [{"review_id": review.id, "quote": "Never said this"}]}]
    recovered = Analyzer(Settings(_env_file=None)).recover(output, [review])
    assert recovered is not None
    assert recovered.issues == [] and recovered.topics == []


@pytest.mark.asyncio
async def test_persistent_optional_failure_retains_valid_result(monkeypatch):
    review = sample_review()
    output = output_for([review]).model_dump()
    output["topics"] = [{"name": "清洁", "evidence": [{"review_id": review.id, "quote": "the lid is hard to clean"}]}]
    output["usage_insights"] = [{"name": "broken"}]

    async def json_call(*args):
        return output

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(Analyzer, "json_call", json_call)
    monkeypatch.setattr("ad_optimizer.analysis.asyncio.sleep", no_sleep)
    analyzer = Analyzer(Settings(_env_file=None))
    result = await analyzer.extract([review])
    assert result.topics[0].name == "清洁"
    assert analyzer.recovery_warnings
