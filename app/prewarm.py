"""Per-video caching, shared in-flight work, and pre-checking of upcoming videos.

Pre-checking runs the normal pipeline (captions -> summary, claims, rhetoric -> evidence per
claim) in the background and stores every step in the cache, so when the viewer reaches that
video the same requests return at once. If the viewer arrives while a pre-check is still
running, their request joins the work already in flight instead of starting it again.
"""
import asyncio
import hashlib
import json
from typing import Awaitable, Callable

from .analysis import Triage
from .config import get_settings
from .evidence import _cache_dir, cache_key, check_claim
from .transcripts import fetch_transcript, video_id

MAX_AHEAD = 3
_inflight: dict[str, asyncio.Task] = {}
_warming: set[str] = set()
_video_slots = asyncio.Semaphore(2)   # videos pre-checked at the same time
_claim_slots = asyncio.Semaphore(3)   # evidence checks at the same time, across pre-checks


def _done(key: str):
    def callback(task: asyncio.Task) -> None:
        _inflight.pop(key, None)
        if not task.cancelled():
            task.exception()  # mark as retrieved; awaiting callers still receive it

    return callback


async def single_flight(key: str, factory: Callable[[], Awaitable]):
    """Run `factory` once per key at a time; concurrent callers share the same result."""
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(factory())
        _inflight[key] = task
        task.add_done_callback(_done(key))
    return await asyncio.shield(task)


def _read(name: str) -> dict | None:
    try:
        return json.loads((_cache_dir() / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(name: str, value: dict) -> None:
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        (_cache_dir() / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    except OSError:
        pass


async def cached_transcript(url: str) -> dict:
    vid = video_id(url)
    if not vid:
        return await fetch_transcript(url)  # raises invalid_url
    name = f"t-{vid}"
    hit = _read(name)
    if hit:
        return {**hit, "cached": True}

    async def work() -> dict:
        result = await fetch_transcript(vid)
        _write(name, result)
        return result

    return {**(await single_flight(name, work)), "cached": False}


def analysis_key(transcript: str, length: str) -> str:
    raw = f"{get_settings().router_model}|{length}|{transcript}"
    return "a-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def cached_analysis(transcript: str, length: str, run: Callable[[], Awaitable[dict]]) -> dict:
    name = analysis_key(transcript, length)
    hit = _read(name)
    if hit:
        return {**hit, "cached": True}

    async def work() -> dict:
        result = await run()
        # Only a fully successful analysis is stored; a partial failure is retried next time.
        if all(result[part]["status"] == "ok" for part in ("summary", "claims", "manipulation")):
            _write(name, result)
        return result

    return {**(await single_flight(name, work)), "cached": False}


async def shared_check(claim: str, triage: Triage | None, use_cache: bool = True) -> dict:
    if not use_cache:
        return await check_claim(claim, triage=triage, use_cache=False)
    return await single_flight("c-" + cache_key(claim), lambda: check_claim(claim, triage=triage))


async def _warm_one(vid: str, analyze: Callable[[str, str], Awaitable[dict]]) -> None:
    try:
        async with _video_slots:
            transcript = (await cached_transcript(vid))["transcript"]
            result = await analyze(transcript, "short")
            claims = result["claims"].get("claims", []) if result["claims"]["status"] == "ok" else []

            async def one(c: dict) -> None:
                async with _claim_slots:
                    triage = None
                    if c.get("search_queries"):
                        triage = Triage(checkable=True, kind=c["kind"], search_queries=c["search_queries"], key_terms=c.get("key_terms", []))
                    try:
                        await shared_check(c["text"], triage)
                    except Exception:
                        pass  # the viewer's own request will retry and show the error

            await asyncio.gather(*(one(c) for c in claims if c.get("checkable")))
    except Exception:
        pass  # a failed pre-check costs nothing: the normal flow runs when the viewer arrives
    finally:
        _warming.discard(vid)


def prewarm(urls: list[str], analyze: Callable[[str, str], Awaitable[dict]]) -> dict:
    queued, skipped = [], []
    for url in urls[:MAX_AHEAD]:
        vid = video_id(url)
        if not vid:
            continue
        if vid in _warming:
            skipped.append(vid)
            continue
        _warming.add(vid)
        asyncio.ensure_future(_warm_one(vid, analyze))
        queued.append(vid)
    return {"status": "ok", "queued": queued, "already_running": skipped}
