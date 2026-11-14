// Side panel: shows the Receipts results page and tells it which video is on screen.
const SERVER = "https://srv2160433.hstgr.cloud";

const frame = document.getElementById("app");
const auto = document.getElementById("auto");
const checkBtn = document.getElementById("check");
const msg = document.getElementById("msg");
const pre = document.getElementById("pre");
const ahead = document.getElementById("ahead");
const prechecked = new Set();   // Shorts already sent for pre-checking in this panel session

let ready = false;      // the results page has loaded and is listening
let shownId = null;     // video currently shown in the results page
let waiting = null;     // video seen while auto-check is off, or before the page was ready
let activeTabId = null;

function toPage(message) {
  frame.contentWindow.postMessage(message, SERVER);
}
function show(video) {
  if (!ready) { waiting = video; return; }
  waiting = null;
  checkBtn.hidden = true;
  if (!video) {
    shownId = null;
    toPage({ type: "receipts:idle", message: "Open a YouTube video or Short and it will be checked here." });
    return;
  }
  if (video.id === shownId) return;
  shownId = video.id;
  toPage({ type: "receipts:video", url: video.url, title: video.title });
}
function onVideo(video) {
  if (auto.checked || !video) return show(video);
  if (video.id === shownId) return;
  waiting = video;
  checkBtn.hidden = false;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}
async function askCurrent() {
  const tab = await activeTab();
  if (!tab) return;
  activeTabId = tab.id;
  try {
    const res = await chrome.tabs.sendMessage(tab.id, { type: "receipts:get-current" });
    onVideo(res ? res.video : null);
  } catch (e) {
    // No content script in this tab: not YouTube, or the tab was open before the extension was installed.
    show(null);
  }
}

// Messages from the YouTube tab.
chrome.runtime.onMessage.addListener((m, sender) => {
  if (!m || !sender.tab || !sender.tab.active) return;
  if (m.type === "receipts:video") {
    activeTabId = sender.tab.id;
    ahead.textContent = "";
    onVideo(m.video);
  } else if (m.type === "receipts:upcoming") {
    if (!ready || !auto.checked || !pre.checked) return;
    const urls = (m.urls || []).filter((u) => !prechecked.has(u)).slice(0, 3);
    if (!m.urls || !m.urls.length) { ahead.textContent = "Could not see the upcoming Shorts on this page."; return; }
    urls.forEach((u) => prechecked.add(u));
    if (urls.length) toPage({ type: "receipts:prewarm", urls });
    ahead.textContent = "Pre-checking the next " + m.urls.length + " Short" + (m.urls.length === 1 ? "" : "s") + ".";
  }
});
chrome.tabs.onActivated.addListener(() => askCurrent());

// Messages from the results page.
window.addEventListener("message", async (ev) => {
  if (ev.origin !== SERVER) return;
  const m = ev.data || {};
  if (m.type === "receipts:ready") {
    ready = true;
    msg.hidden = true;
    if (waiting && auto.checked) show(waiting);
    else askCurrent();
  } else if (m.type === "receipts:need-transcript") {
    let transcript = null;
    try {
      const res = await chrome.tabs.sendMessage(activeTabId, { type: "receipts:get-transcript" });
      transcript = res ? res.transcript : null;
    } catch (e) {}
    toPage({ type: "receipts:transcript-result", url: m.url, transcript });
  } else if (m.type === "receipts:score" && activeTabId != null) {
    const colors = { low: "#1f6f43", some: "#b07400", high: "#b3261e", none: "#6b655b" };
    const text = m.score == null ? "" : String(m.score);
    chrome.action.setBadgeText({ tabId: activeTabId, text }).catch(() => {});
    chrome.action.setBadgeBackgroundColor({ tabId: activeTabId, color: colors[m.level] || colors.none }).catch(() => {});
  }
});

checkBtn.onclick = () => { if (waiting) show(waiting); };
auto.onchange = () => {
  chrome.storage.local.set({ auto: auto.checked });
  if (auto.checked && waiting) show(waiting);
};

pre.onchange = () => chrome.storage.local.set({ pre: pre.checked });

chrome.storage.local.get({ auto: true, pre: true }, (s) => {
  auto.checked = s.auto;
  pre.checked = s.pre;
  msg.textContent = "Connecting to the Receipts server…";
  msg.hidden = false;
  frame.src = SERVER + "/?embed=1";
  setTimeout(() => {
    if (!ready) msg.textContent = "The Receipts server could not be reached. Check your connection and reopen this panel.";
  }, 12000);
});
