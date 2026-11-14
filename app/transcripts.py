"""Fetch a YouTube transcript by URL, server side.

Best effort only: YouTube often blocks requests from data-centre addresses. When that
happens we say so and the user can paste the transcript or use the browser extension,
which reads captions in the user's own browser.
"""
import asyncio
import re

_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})")
_BARE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class TranscriptError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def video_id(url: str) -> str | None:
    url = url.strip()
    if _BARE.match(url):
        return url
    m = _ID.search(url)
    return m.group(1) if m else None


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def format_segments(segments: list[tuple[float, str]], every: float = 20.0) -> str:
    """Join caption segments into lines that start with a [m:ss] timestamp about every `every` seconds."""
    lines, current, line_start, last_mark = [], [], 0.0, None
    for start, text in segments:
        text = " ".join(text.split())
        if not text:
            continue
        if last_mark is None or start - last_mark >= every:
            if current:
                lines.append(f"[{stamp(line_start)}] " + " ".join(current))
            current, line_start, last_mark = [], start, start
        current.append(text)
    if current:
        lines.append(f"[{stamp(line_start)}] " + " ".join(current))
    return "\n".join(lines)


def _fetch_sync(vid: str) -> dict:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled, VideoUnavailable,
    )

    try:
        fetched = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US", "en-GB"])
    except NoTranscriptFound:
        try:  # no English captions: take whatever language exists
            listing = YouTubeTranscriptApi().list(vid)
            fetched = next(iter(listing)).fetch()
        except (RequestBlocked, IpBlocked):
            raise TranscriptError("blocked", "YouTube refused our server's request for this transcript.")
        except Exception:
            raise TranscriptError("no_transcript", "No transcript is available for this video.")
    except TranscriptsDisabled:
        raise TranscriptError("no_transcript", "No transcript is available for this video.")
    except VideoUnavailable:
        raise TranscriptError("no_video", "This video is unavailable.")
    except (RequestBlocked, IpBlocked):
        raise TranscriptError("blocked", "YouTube refused our server's request for this transcript.")
    except Exception:
        raise TranscriptError("fetch_failed", "The transcript could not be fetched from YouTube.")
    text = format_segments([(s.start, s.text) for s in fetched])
    if len(text) < 40:
        raise TranscriptError("no_transcript", "No transcript is available for this video.")
    return {"video_id": vid, "language": fetched.language_code, "auto_generated": fetched.is_generated, "transcript": text}


async def fetch_transcript(url: str) -> dict:
    vid = video_id(url)
    if not vid:
        raise TranscriptError("invalid_url", "That does not look like a YouTube video link.")
    return await asyncio.to_thread(_fetch_sync, vid)
