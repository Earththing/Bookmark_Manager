// Bookmark Manager Helper Extension
// This extension allows the Bookmark Manager desktop app to delete bookmarks
// using the official Chrome Bookmarks API, which properly syncs deletions.

// Listen for messages from the native messaging host
chrome.runtime.onMessageExternal.addListener(
  (request, sender, sendResponse) => {
    if (request.action === 'deleteBookmarks') {
      deleteBookmarks(request.bookmarkIds)
        .then(results => sendResponse({ success: true, results }))
        .catch(error => sendResponse({ success: false, error: error.message }));
      return true; // Keep the message channel open for async response
    }

    if (request.action === 'ping') {
      sendResponse({ success: true, message: 'Extension is active' });
      return true;
    }

    if (request.action === 'findBookmarksByUrl') {
      findBookmarksByUrl(request.urls)
        .then(results => sendResponse({ success: true, results }))
        .catch(error => sendResponse({ success: false, error: error.message }));
      return true;
    }
  }
);

// Also support native messaging for direct communication
chrome.runtime.onConnectExternal.addListener((port) => {
  port.onMessage.addListener(async (message) => {
    if (message.action === 'deleteBookmarks') {
      try {
        const results = await deleteBookmarks(message.bookmarkIds);
        port.postMessage({ success: true, results });
      } catch (error) {
        port.postMessage({ success: false, error: error.message });
      }
    }
  });
});

/**
 * Delete bookmarks by their IDs using the Chrome Bookmarks API.
 * This properly propagates the deletion to sync servers.
 */
async function deleteBookmarks(bookmarkIds) {
  const results = [];

  for (const id of bookmarkIds) {
    try {
      // Convert to string if needed (Chrome API expects string IDs)
      const idStr = String(id);
      await chrome.bookmarks.remove(idStr);
      results.push({ id: idStr, success: true });
    } catch (error) {
      results.push({ id: String(id), success: false, error: error.message });
    }
  }

  return results;
}

/**
 * Find bookmarks by URL and return their IDs.
 * Useful for finding bookmarks when we have URLs but not IDs.
 */
async function findBookmarksByUrl(urls) {
  const results = [];

  for (const url of urls) {
    try {
      const bookmarks = await chrome.bookmarks.search({ url });
      results.push({
        url,
        bookmarks: bookmarks.map(b => ({
          id: b.id,
          title: b.title,
          url: b.url,
          parentId: b.parentId
        }))
      });
    } catch (error) {
      results.push({ url, error: error.message, bookmarks: [] });
    }
  }

  return results;
}

// Log when extension is loaded
console.log('Bookmark Manager Helper extension loaded');
