// Clicking the toolbar icon opens the side panel.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

// Clear the score badge when a tab navigates to a different page.
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === "receipts:video" && sender.tab) {
    chrome.action.setBadgeText({ tabId: sender.tab.id, text: "" }).catch(() => {});
  }
});
