import pytest
from fastapi.testclient import TestClient

from app.analysis import TranscriptIndex
from app.limits import limiter
from app.main import app
from app.stats import proportion, wilson
from tests.test_stage1 import chat, configure

client = TestClient(app)
T = """[0:00] Coffee is the most consumed drink on earth after water.
[0:08] A big study found people who drink three to four cups a day have a lower
[0:15] risk of diabetes. Honestly I think everyone should drink it.
[0:24] Millions of people can't be wrong. Wake up, people!"""


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER_MODEL", raising=False)
    limiter.reset()


def test_index_finds_quote_and_timestamp():
    idx = TranscriptIndex(T)
    assert idx.has_timestamps
    assert idx.locate("Coffee is the most consumed drink") == (True, "0:00")
    assert idx.locate("millions of people can't be wrong") == (True, "0:24")


def test_index_matches_quote_spanning_a_timestamp_line():
    assert TranscriptIndex(T).locate("have a lower risk of diabetes") == (True, "0:08")


def test_index_rejects_text_not_in_transcript():
    idx = TranscriptIndex(T)
    assert idx.locate("coffee cures cancer") == (False, None)
    assert idx.locate("consumed drink on mars") == (False, None)


def test_index_without_timestamps():
    idx = TranscriptIndex("Coffee is great. Tea is fine too, people say.")
    assert not idx.has_timestamps
    assert idx.locate("tea is fine too") == (True, None)


def test_plain_numbers_are_not_timestamps():
    idx = TranscriptIndex("The ratio was 3:1 in the trial and it ended at noon, and so on and on.")
    assert idx.locate("the ratio was 3:1 in the trial") == (True, None)


CLAIMS = """{"claims": [
 {"text": "Coffee is the most consumed drink after water.", "quote": "Coffee is the most consumed drink on earth after water.", "kind": "scientific", "checkable": true, "why_not_checkable": null},
 {"text": "Everyone should drink coffee.", "quote": "Honestly I think everyone should drink it.", "kind": "scientific", "checkable": false, "why_not_checkable": "opinion"},
 {"text": "Coffee cures cancer.", "quote": "coffee cures all cancer", "kind": "scientific", "checkable": true, "why_not_checkable": null}]}"""


def test_claims_endpoint_verifies_quotes(monkeypatch):
    configure(monkeypatch, [chat(CLAIMS)])
    r = client.post("/claims", json={"transcript": T})
    assert r.status_code == 200
    d = r.json()
    assert d["counts"] == {"total": 3, "checkable": 2, "not_checkable": 1, "quotes_unverified": 1}
    c1, c2, c3 = d["claims"]
    assert (c1["timestamp"], c1["quote_verified"]) == ("0:00", True)
    assert c2["why_not_checkable"] == "opinion" and c2["timestamp"] == "0:15"
    assert c3["quote"] is None and c3["quote_verified"] is False  # invented quote is never shown


def test_claims_empty_is_a_valid_result(monkeypatch):
    configure(monkeypatch, [chat('{"claims": []}')])
    d = client.post("/claims", json={"transcript": T}).json()
    assert d["status"] == "ok" and d["claims"] == []


FLAGS = """{"flags": [
 {"technique": "bandwagon", "quote": "Millions of people can't be wrong.", "explanation": "Popularity is used as proof."},
 {"technique": "slogans", "quote": "Rise and grind!", "explanation": "Invented quote."},
 {"technique": "made_up_technique", "quote": "Wake up, people!", "explanation": "Unknown id."}]}"""


def test_manipulation_drops_unverified_and_unknown(monkeypatch):
    configure(monkeypatch, [chat(FLAGS)])
    d = client.post("/manipulation", json={"transcript": T}).json()
    assert [f["technique"] for f in d["flags"]] == ["bandwagon"]
    assert d["flags"][0]["timestamp"] == "0:24"
    assert d["counts"]["dropped_unverified"] == 2
    assert len(d["techniques_checked"]) == 12


def test_analyze_parts_fail_independently(monkeypatch):
    # every router reply is invalid JSON for all three parts
    configure(monkeypatch, [chat("nope")])
    r = client.post("/analyze", json={"transcript": T})
    assert r.status_code == 200
    d = r.json()
    for part in ("summary", "claims", "manipulation"):
        assert d[part]["status"] == "error" and d[part]["error"] == "analysis_failed"


def test_wilson_known_values():
    lo, hi = wilson(8, 10)
    assert round(lo, 3) == 0.490 and round(hi, 3) == 0.943
    assert wilson(0, 0) is None
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and round(hi, 3) == 0.278


def test_proportion_flags_small_samples():
    assert proportion(5, 10)["too_small"] is True
    assert proportion(15, 30)["too_small"] is False
    assert proportion(0, 0)["value"] is None
