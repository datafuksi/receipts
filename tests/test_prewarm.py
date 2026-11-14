import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import prewarm as pw
from app.limits import limiter
from app.main import app
from tests.test_stage1 import chat, configure

client = TestClient(app)
T = "[0:00] Coffee is the most consumed drink on earth after water. Honestly I think everyone should drink it all day."
ANALYSIS = [
    chat('{"summary": "About coffee.", "key_points": []}'),
    chat('{"claims": []}'),
    chat('{"flags": []}'),
]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    limiter.reset()
    pw._warming.clear()


def test_single_flight_shares_one_run():
    runs = 0

    async def work():
        nonlocal runs
        runs += 1
        await asyncio.sleep(0.05)
        return "done"

    async def main():
        return await asyncio.gather(*(pw.single_flight("k", work) for _ in range(5)))

    assert asyncio.run(main()) == ["done"] * 5
    assert runs == 1


def test_analysis_is_cached_after_a_full_success(monkeypatch):
    calls = configure(monkeypatch, ANALYSIS)
    first = client.post("/analyze", json={"transcript": T}).json()
    n = len(calls)
    second = client.post("/analyze", json={"transcript": T}).json()
    assert first["cached"] is False and second["cached"] is True
    assert n == 3 and len(calls) == 3  # the second request made no AI calls
    assert second["summary"]["summary"] == "About coffee."


def test_partial_failure_is_not_cached(monkeypatch):
    configure(monkeypatch, [chat("not json")])
    client.post("/analyze", json={"transcript": T})
    assert client.post("/analyze", json={"transcript": T}).json()["cached"] is False


def test_transcript_is_cached_per_video(monkeypatch):
    fetches = []

    async def fake(url):
        fetches.append(url)
        return {"video_id": "abcdefghijk", "language": "en", "auto_generated": True, "transcript": T}

    monkeypatch.setattr(pw, "fetch_transcript", fake)
    a = client.post("/transcript", json={"url": "https://www.youtube.com/shorts/abcdefghijk"}).json()
    b = client.post("/transcript", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}).json()
    assert a["cached"] is False and b["cached"] is True and len(fetches) == 1


def test_prewarm_fills_the_cache_for_upcoming_videos(monkeypatch, tmp_path):
    configure(monkeypatch, ANALYSIS)

    async def by_prompt(payload, settings):  # two videos run at once, so answer by task, not by order
        system = payload["messages"][0]["content"]
        if "summarize" in system:
            return ANALYSIS[0]
        return ANALYSIS[1] if "factual claims" in system else ANALYSIS[2]

    from app import llm

    monkeypatch.setattr(llm, "_post_chat", by_prompt)

    async def fake(url):
        return {"video_id": url, "language": "en", "auto_generated": True, "transcript": T + " " + url}

    monkeypatch.setattr(pw, "fetch_transcript", fake)

    async def main():
        out = pw.prewarm(["https://www.youtube.com/shorts/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb", "nope"], app_analyze)
        again = pw.prewarm(["https://www.youtube.com/shorts/aaaaaaaaaaa"], app_analyze)
        for _ in range(100):
            if not pw._warming:
                break
            await asyncio.sleep(0.02)
        return out, again

    from app.main import _analyze as app_analyze

    out, again = asyncio.run(main())
    assert out["queued"] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert again["already_running"] == ["aaaaaaaaaaa"]
    names = sorted(p.name[:2] for p in tmp_path.iterdir())
    assert names.count("t-") == 2 and names.count("a-") == 2


def test_prewarm_endpoint_limits_to_three():
    r = client.post("/prewarm", json={"urls": ["a" * 11] * 4})
    assert r.status_code == 422
