import json

import pytest
from fastapi.testclient import TestClient

from app import evidence as ev
from app.analysis import Triage, claim_budget
from app.limits import limiter
from app.main import app
from app.transcripts import format_segments, video_id
from tests.test_stage1 import chat, configure

client = TestClient(app)

PAPER = ev.Source(
    title="Coffee consumption and risk of type 2 diabetes: a meta-analysis",
    url="https://doi.org/10.1/abc",
    text="Coffee consumption was inversely associated with the risk of type 2 diabetes in a dose-response manner. Both caffeinated and decaffeinated coffee were associated with reduced diabetes risk.",
    source_type="research", authors="Ding M, Chen M", year="2014", venue="Diabetes Care", pub_types=["Meta-Analysis"],
)
OTHER = ev.Source(
    title="Coffee and incident diabetes in a cohort", url="https://doi.org/10.1/def",
    text="Participants who drank more coffee had a lower incidence of type 2 diabetes over ten years of follow-up.",
    source_type="research", authors="Lee A", year="2019", venue="BMJ",
)
OFFTOPIC = ev.Source(title="Tea and bone density", url="https://doi.org/10.1/zzz", text="Tea drinkers had higher bone density.", source_type="research")
TRIAGE = Triage(checkable=True, kind="scientific", search_queries=["coffee type 2 diabetes"], key_terms=["coffee", "diabetes"])
CLAIM = "Drinking coffee lowers the risk of type 2 diabetes."


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    limiter.reset()

    async def research(queries, per_query=6):
        return [PAPER, OTHER, OFFTOPIC], False

    monkeypatch.setattr(ev, "search_research", research)


def verdict(v, cites, caveats=()):
    return chat(json.dumps({"verdict": v, "explanation": "Because the sources say so.", "caveats": list(caveats), "citations": cites}))


def test_relevance_filter_drops_off_topic():
    kept = ev.filter_relevant([PAPER, OTHER, OFFTOPIC], CLAIM, ["coffee", "diabetes"])
    assert [s.url for s in kept] == [PAPER.url, OTHER.url]


def test_snippet_must_be_in_source_text():
    assert ev._snippet_in("inversely associated with the risk of type 2 diabetes", PAPER.text)
    assert not ev._snippet_in("coffee cures diabetes completely", PAPER.text)


def test_confidence_rule():
    assert ev.confidence_for("supported", [PAPER, OTHER])[0] == "high"      # two sources, one meta-analysis
    assert ev.confidence_for("supported", [OTHER, OTHER])[0] == "medium"    # two sources, no review
    assert ev.confidence_for("supported", [OTHER])[0] == "low"
    assert ev.confidence_for("mixed", [PAPER, OTHER])[0] == "medium"        # mixed is never high
    assert ev.confidence_for("not_enough_data", [])[0] is None


def test_supported_with_verified_citations(monkeypatch):
    configure(monkeypatch, [verdict("supported", [
        {"source": "S1", "stance": "supports", "snippet": "Coffee consumption was inversely associated with the risk of type 2 diabetes in a dose-response manner."},
        {"source": "S2", "stance": "supports", "snippet": "Participants who drank more coffee had a lower incidence of type 2 diabetes"},
    ])])
    r = client.post("/check", json={"claim": CLAIM, "kind": "scientific", "search_queries": ["coffee diabetes"], "key_terms": ["coffee", "diabetes"]})
    d = r.json()
    assert r.status_code == 200 and d["verdict"] == "supported" and d["confidence"] == "high"
    assert d["citations"][0]["title"] == PAPER.title and d["citations"][0]["url"] == PAPER.url  # metadata from the API
    assert d["source_type"] == "research" and d["abstained"] is False


def test_invented_snippet_withdraws_the_verdict(monkeypatch):
    configure(monkeypatch, [verdict("supported", [{"source": "S1", "stance": "supports", "snippet": "Coffee completely prevents diabetes in all adults."}])])
    d = client.post("/check", json={"claim": CLAIM, "kind": "scientific", "search_queries": ["q"], "key_terms": ["coffee", "diabetes"]}).json()
    assert d["verdict"] == "not_enough_data" and d["citations"] == [] and d["abstained"] is True
    assert d["searched"]["citations_dropped_unverified"] == 1


def test_unknown_source_id_is_dropped(monkeypatch):
    configure(monkeypatch, [verdict("not_supported", [{"source": "S9", "stance": "contradicts", "snippet": "A paper that was never retrieved says otherwise."}])])
    d = client.post("/check", json={"claim": CLAIM, "kind": "scientific", "search_queries": ["q"], "key_terms": ["coffee", "diabetes"]}).json()
    assert d["verdict"] == "not_enough_data"


def test_no_sources_is_not_enough_data_without_calling_the_model(monkeypatch):
    calls = configure(monkeypatch, [verdict("supported", [])])

    async def nothing(queries, per_query=6):
        return [], False

    async def no_web(query, size=6):
        return []

    monkeypatch.setattr(ev, "search_research", nothing)
    monkeypatch.setattr(ev, "search_web", no_web)
    d = client.post("/check", json={"claim": CLAIM, "kind": "scientific", "search_queries": ["q"], "key_terms": ["coffee", "diabetes"]}).json()
    assert d["verdict"] == "not_enough_data" and calls == []


def test_opinion_is_not_checkable_and_runs_no_search(monkeypatch):
    configure(monkeypatch, [chat('{"checkable": false, "kind": "news", "why_not_checkable": "opinion", "search_queries": [], "key_terms": []}')])

    async def boom(*a, **k):
        raise AssertionError("search must not run for an opinion")

    monkeypatch.setattr(ev, "search_research", boom)
    monkeypatch.setattr(ev, "search_web", boom)
    d = client.post("/check", json={"claim": "Pineapple on pizza is disgusting."}).json()
    assert d["verdict"] == "not_checkable" and d["abstained"] is True and d["confidence"] is None


def test_result_is_cached_and_offline_mode_uses_only_cache(monkeypatch):
    calls = configure(monkeypatch, [verdict("supported", [{"source": "S1", "stance": "supports", "snippet": "Both caffeinated and decaffeinated coffee were associated with reduced diabetes risk."}])])
    body = {"claim": CLAIM, "kind": "scientific", "search_queries": ["q"], "key_terms": ["coffee", "diabetes"]}
    first = client.post("/check", json=body).json()
    second = client.post("/check", json=body).json()
    assert first["cached"] is False and second["cached"] is True and len(calls) == 1
    monkeypatch.setenv("OFFLINE_MODE", "1")
    assert client.post("/check", json=body).json()["cached"] is True
    miss = client.post("/check", json={"claim": "Some other claim never seen before."})
    assert miss.status_code == 404 and miss.json()["error"] == "offline_miss"


def test_claim_budget_scales_with_length():
    assert claim_budget("word " * 150) == 4
    assert claim_budget("word " * 1500) == 12
    assert claim_budget("word " * 9000) == 30


def test_video_id_and_segment_formatting():
    assert video_id("https://www.youtube.com/watch?v=c0WHTlLwJlk&t=3") == "c0WHTlLwJlk"
    assert video_id("https://youtube.com/shorts/abcdefghijk?feature=share") == "abcdefghijk"
    assert video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert video_id("https://example.com/") is None
    text = format_segments([(0.0, "hello"), (5.0, "there"), (25.0, "new line"), (3700.0, "late")])
    assert text == "[0:00] hello there\n[0:25] new line\n[1:01:40] late"


def test_bad_url_is_rejected():
    r = client.post("/transcript", json={"url": "https://example.com/not-a-video"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_url"
