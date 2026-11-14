"""Run the labelled test set through the real pipeline and write measured results.

Usage (from the repo root, with .env present):
    python scripts/metrics.py triage      # stage 2: checkable vs not checkable
Every number written comes from this run; nothing is filled in by hand.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.analysis import triage_claim  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.stats import proportion  # noqa: E402

OUT = ROOT / "data" / "metrics"


async def run_triage(items: list[dict]) -> dict:
    sem = asyncio.Semaphore(5)

    async def one(item: dict) -> dict:
        async with sem:
            try:
                t = await triage_claim(item["claim"])
                return {**item, "got_checkable": t.checkable, "got_kind": t.kind, "error": None}
            except LLMError as exc:
                return {**item, "got_checkable": None, "got_kind": None, "error": exc.kind}

    rows = await asyncio.gather(*(one(i) for i in items))
    done = [r for r in rows if r["error"] is None]
    for r in done:
        r["want_checkable"] = r["expected"] != "not_checkable"
        r["correct"] = r["got_checkable"] == r["want_checkable"]
    opinions = [r for r in done if not r["want_checkable"]]
    factual = [r for r in done if r["want_checkable"]]
    return {
        "task": "triage: is the claim checkable (fact) or not checkable (opinion or prediction)?",
        "model": get_settings().router_model,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_items": len(rows),
        "n_failed_calls": len(rows) - len(done),
        "accuracy": proportion(sum(r["correct"] for r in done), len(done)),
        "abstains_on_uncheckable": proportion(sum(r["correct"] for r in opinions), len(opinions)),
        "accepts_checkable": proportion(sum(r["correct"] for r in factual), len(factual)),
        "kind_agreement": proportion(sum(r["got_kind"] == r["kind"] for r in factual), len(factual)),
        "errors": [r for r in rows if r["error"] or not r.get("correct")],
        "rows": rows,
    }


def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else "triage"
    items = json.loads((ROOT / "data" / "testset.json").read_text(encoding="utf-8"))["claims"]
    if task != "triage":
        sys.exit(f"unknown task {task!r} (the verdict task is added in stage 3)")
    result = asyncio.run(run_triage(items))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "triage.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for key in ("accuracy", "abstains_on_uncheckable", "accepts_checkable", "kind_agreement"):
        m = result[key]
        ci = f"{m['ci95'][0]:.2f}-{m['ci95'][1]:.2f}" if m["ci95"] else "n/a"
        small = "  (n too small to claim anything)" if m["too_small"] else ""
        print(f"{key:26s} {m['successes']}/{m['n']}  95% CI {ci}{small}")
    print("failed calls:", result["n_failed_calls"])
    for r in result["errors"]:
        print("  MISS", r["id"], "| expected", r["expected"], "| got_checkable", r["got_checkable"], "|", r["claim"])


if __name__ == "__main__":
    main()
