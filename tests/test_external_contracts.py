import json

import httpx
import pytest

from ad_optimizer.analysis import Analyzer
from ad_optimizer.config import Settings
from ad_optimizer.providers import BrightData, ServiceError


def config():
    return Settings(_env_file=None, bright_data_api_key="test-only", bright_data_dataset_id="test", llm_api_key="test-only", provider_poll_seconds=.1)


def mock_http(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_bright_data_http_contract_without_time_window(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/trigger"):
            payload = json.loads(request.content)
            assert payload == [{"url": "https://www.amazon.com/dp/B012345678", "numOfReviews": 100}]
            assert "pastDays" not in payload[0]
            assert request.url.params["dataset_id"] == "test"
            return httpx.Response(200, json={"snapshot_id": "s_test"})
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json=[{"review_id": "one", "rating": 2, "review_text": "Stopped working.", "review_date": "2025-01-01"}])
    mock_http(monkeypatch, handler)
    report = await BrightData(config()).collect("B012345678")
    assert report.total == 1 and report.negative_percentage == 100.0
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_bright_data_returned_error_is_not_empty_success(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/trigger"):
            return httpx.Response(200, json={"snapshot_id": "s_test"})
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json=[{"error": "could not collect", "url": "https://www.amazon.com/dp/B012345678"}])
    mock_http(monkeypatch, handler)
    with pytest.raises(ServiceError) as error:
        await BrightData(config()).collect("B012345678")
    assert error.value.code == "PROVIDER_REQUEST_ERROR"


@pytest.mark.asyncio
async def test_trigger_timeout_is_not_retried(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("test", request=request)
    mock_http(monkeypatch, handler)
    with pytest.raises(ServiceError) as error:
        await BrightData(config()).collect("B012345678")
    assert error.value.code == "PROVIDER_TIMEOUT" and len(calls) == 1


@pytest.mark.asyncio
async def test_model_json_and_endpoint_contract(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]})
    mock_http(monkeypatch, handler)
    assert await Analyzer(config()).json_call("json", "test") == {"ok": True}


@pytest.mark.asyncio
async def test_model_truncation_rejected(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"ok": true}'}}]}))
    with pytest.raises(ValueError):
        await Analyzer(config()).json_call("json", "test")
