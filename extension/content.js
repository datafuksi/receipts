// Runs on youtube.com. It only watches which video is on screen and tells the side panel.
// Nothing is sent to our server from here; the side panel does that, and only while it is open.

function currentVideo() {
  const u = new URL(location.href);
  let id = null;
  const short = u.pathname.match(/^\/shorts\/([A-Za-z0-9_-]{11})/);
  if (short) id = short[1];
  else if (u.pathname === "/watch") id = u.searchParams.get("v");
  if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) return null;
  return {
    id,
    url: short ? "https://www.youtube.com/shorts/" + id : "https://www.youtube.com/watch?v=" + id,
    kind: short ? "short" : "video",
    title: document.title.replace(/^\(\d+\)\s*/, "").replace(/\s*-\s*YouTube$/, "").trim(),
  };
}

function send(message) {
  try {
    chrome.runtime.sendMessage(message, () => void chrome.runtime.lastError);
  } catch (e) {
    /* extension was reloaded; this page needs a refresh */
  }
}

// Shorts the page has already lined up after the one on screen. YouTube renders the next few
// reels ahead of time; we read their video ids from links and thumbnails already in the page.
// Best effort: if YouTube changes its markup this returns an empty list and nothing is pre-checked.
function upcomingShorts(currentId, max) {
  const reels = Array.from(document.querySelectorAll("ytd-reel-video-renderer, .reel-video-in-sequence, .reel-video-in-sequence-new"));
  const idOf = (node) => {
    const html = node.innerHTML;
    const m = html.match(/\/shorts\/([A-Za-z0-9_-]{11})/) || html.match(/\/vi(?:_webp)?\/([A-Za-z0-9_-]{11})\//);
    return m ? m[1] : null;
  };
  let at = reels.findIndex((r) => r.hasAttribute("is-active"));
  if (at < 0) at = reels.findIndex((r) => idOf(r) === currentId);
  if (at < 0) return [];
  const ids = [];
  for (const reel of reels.slice(at + 1)) {
    const id = idOf(reel);
    if (id && id !== currentId && !ids.includes(id)) ids.push(id);
    if (ids.length >= max) break;
  }
  return ids;
}

let lastId = undefined;
let timer = null;
let aheadTimer = null;

function announceAhead(forId) {
  const v = currentVideo();
  if (!v || v.id !== forId || v.kind !== "short") return;
  const ids = upcomingShorts(v.id, 3);
  send({ type: "receipts:upcoming", forId: v.id, urls: ids.map((id) => "https://www.youtube.com/shorts/" + id) });
}

function announce() {
  const v = currentVideo();
  send(v ? { type: "receipts:video", video: v } : { type: "receipts:video", video: null });
  clearTimeout(aheadTimer);
  // Give YouTube a moment to line up the next reels before looking for them.
  if (v && v.kind === "short") aheadTimer = setTimeout(() => announceAhead(v.id), 1500);
}

// YouTube is a single-page app: the address changes without a page load, including when
// scrolling through Shorts. Poll the address and wait until it has settled before announcing,
// so flicking past several Shorts only checks the one you stop on.
setInterval(() => {
  const v = currentVideo();
  const id = v ? v.id : null;
  if (id === lastId) return;
  lastId = id;
  clearTimeout(timer);
  timer = setTimeout(announce, 1200);
}, 400);

function stamp(seconds) {
  const s = Math.floor(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? h + ":" + two(m) + ":" + two(sec) : m + ":" + two(sec);
}

// Fallback used only when our server could not fetch the captions: read the transcript the
// page itself already shows, if the viewer has opened YouTube's "Show transcript" panel.
function transcriptFromPage() {
  const rows = document.querySelectorAll("ytd-transcript-segment-renderer");
  if (!rows.length) return null;
  const lines = [];
  rows.forEach((row) => {
    const time = (row.querySelector(".segment-timestamp") || {}).textContent || "";
    const text = (row.querySelector(".segment-text") || {}).textContent || "";
    if (text.trim()) lines.push("[" + time.trim() + "] " + text.trim().replace(/\s+/g, " "));
  });
  const joined = lines.join("\n");
  return joined.length >= 40 ? joined : null;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg) return;
  if (msg.type === "receipts:get-current") {
    const v = currentVideo();
    reply({ video: v });
    if (v && v.kind === "short") setTimeout(() => announceAhead(v.id), 1500);
  }
  else if (msg.type === "receipts:get-transcript") reply({ transcript: transcriptFromPage() });
});
