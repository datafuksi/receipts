import pytest
from fastapi.testclient import TestClient

from app import llm
from app.limits import limiter
from app.main import app

client = TestClient(app)
TRANSCRIPT = "Coffee is the most consumed drink on earth after water, and studies say it cuts the risk of diabetes. " * 2


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER_MODEL", raising=False)
    limiter.reset()


def configure(monkeypatch, replies):
    """Configure a fake router that returns each reply in turn; returns the call log."""
    monkeypatch.setenv("ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_MODEL", "test-model")
    calls = []

    async def fake_post(payload, settings):
        calls.append(payload)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm, "_post_chat", fake_post)
    return calls


def chat(content, **extra):
    return {"choices": [{"message": {"content": content, **extra}, "finish_reason": "stop"}]}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["llm_configured"] is False


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Receipts" in r.text


def test_summarize_without_key_is_an_error_not_a_default():
    r = client.post("/summarize", json={"transcript": TRANSCRIPT})
    assert r.status_code == 503
    assert r.json()["error"] == "not_configured"
    assert "summary" not in r.json()


def test_summarize_ok(monkeypatch):
    calls = configure(monkeypatch, [chat('{"summary": "About coffee.", "key_points": ["Popular drink"]}')])
    r = client.post("/summarize", json={"transcript": TRANSCRIPT, "length": "long"})
    assert r.status_code == 200
    assert r.json()["summary"] == "About coffee."
    assert r.json()["length"] == "long"
    assert calls[0]["temperature"] == 0


def test_fenced_json_is_accepted(monkeypatch):
    configure(monkeypatch, [chat('```json\n{"summary": "S", "key_points": []}\n```')])
    assert client.post("/summarize", json={"transcript": TRANSCRIPT}).status_code == 200


def test_parse_failure_retries_once_then_succeeds(monkeypatch):
    calls = configure(monkeypatch, [chat("not json"), chat('{"summary": "S", "key_points": []}')])
    r = client.post("/summarize", json={"transcript": TRANSCRIPT})
    assert r.status_code == 200
    assert len(calls) == 2


def test_parse_failure_twice_is_analysis_failed(monkeypatch):
    calls = configure(monkeypatch, [chat("not json")])
    r = client.post("/summarize", json={"transcript": TRANSCRIPT})
    assert r.status_code == 502
    assert r.json()["error"] == "analysis_failed"
    assert len(calls) == 2  # exactly one retry


def test_refusal_is_surfaced_without_retry(monkeypatch):
    calls = configure(monkeypatch, [chat(None, refusal="I can't help with that.")])
    r = client.post("/summarize", json={"transcript": TRANSCRIPT})
    assert r.status_code == 422
    assert r.json()["error"] == "refused"
    assert len(calls) == 1


def test_router_outage(monkeypatch):
    configure(monkeypatch, [llm.LLMError("router_unavailable", "down")])
    r = client.post("/summarize", json={"transcript": TRANSCRIPT})
    assert r.status_code == 502
    assert r.json()["error"] == "router_unavailable"


def test_short_transcript_rejected():
    assert client.post("/summarize", json={"transcript": "too short"}).status_code == 422


def test_unbuilt_endpoint_says_so():
    r = client.post("/check", json={"claim": "Coffee reduces diabetes risk."})
    assert r.status_code == 501
    assert r.json()["error"] == "not_implemented"


def test_rate_limit(monkeypatch):
    monkeypatch.setenv("RATE_PER_MIN", "3")
    codes = [client.post("/check", json={"claim": "Coffee reduces diabetes risk."}).status_code for _ in range(4)]
    assert codes == [501, 501, 501, 429]


def test_daily_cap(monkeypatch):
    monkeypatch.setenv("DAILY_CAP", "1")
    codes = [client.post("/check", json={"claim": "Coffee reduces diabetes risk."}).status_code for _ in range(2)]
    assert codes[1] == 429
