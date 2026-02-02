document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const loadFileBtn = document.getElementById('loadFileBtn');
  const pasteBtn = document.getElementById('pasteBtn');
  const deleteBtn = document.getElementById('deleteBtn');
  const clearBtn = document.getElementById('clearBtn');
  const bookmarkIdsInput = document.getElementById('bookmarkIds');
  const countDisplay = document.getElementById('count-display');
  const progressDiv = document.getElementById('progress');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');
  const resultsDiv = document.getElementById('results');

  // Update count when text changes
  bookmarkIdsInput.addEventListener('input', updateCount);

  // Load file button
  loadFileBtn.addEventListener('click', () => {
    fileInput.click();
  });

  // File input handler
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      let content = event.target.result;

      // Try to parse as JSON first
      try {
        const json = JSON.parse(content);
        if (Array.isArray(json)) {
          // Array of IDs or objects with id property
          content = json.map(item =>
            typeof item === 'object' ? item.id : item
          ).join('\n');
        }
      } catch (e) {
        // Not JSON, use as-is (text file with IDs)
      }

      bookmarkIdsInput.value = content;
      updateCount();
    };
    reader.readAsText(file);
    fileInput.value = ''; // Reset for same file selection
  });

  // Paste from clipboard
  pasteBtn.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      bookmarkIdsInput.value = text;
      updateCount();
    } catch (error) {
      alert('Could not access clipboard. Please paste manually with Ctrl+V.');
    }
  });

  // Clear button
  clearBtn.addEventListener('click', () => {
    bookmarkIdsInput.value = '';
    resultsDiv.classList.remove('show');
    resultsDiv.innerHTML = '';
    progressDiv.classList.remove('show');
    progressFill.style.width = '0%';
    updateCount();
  });

  // Delete button
  deleteBtn.addEventListener('click', async () => {
    const ids = getIds();
    if (ids.length === 0) {
      alert('No bookmark IDs to delete.');
      return;
    }

    if (!confirm(`Are you sure you want to delete ${ids.length} bookmark(s)?\n\nThis action cannot be undone and will sync to your account.`)) {
      return;
    }

    deleteBtn.disabled = true;
    loadFileBtn.disabled = true;
    pasteBtn.disabled = true;
    clearBtn.disabled = true;
    bookmarkIdsInput.disabled = true;

    progressDiv.classList.add('show');
    resultsDiv.classList.add('show');
    resultsDiv.innerHTML = '';

    let successCount = 0;
    let errorCount = 0;
    const total = ids.length;

    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      const progress = ((i + 1) / total * 100).toFixed(0);
      progressFill.style.width = progress + '%';
      progressText.textContent = `Deleting ${i + 1} of ${total}...`;

      try {
        await chrome.bookmarks.remove(String(id));
        successCount++;
        addResult(true, `Deleted bookmark ID: ${id}`);
      } catch (error) {
        errorCount++;
        addResult(false, `Failed ID ${id}: ${error.message}`);
      }
    }

    progressFill.style.width = '100%';
    progressText.innerHTML = `<strong>Complete!</strong> Deleted: ${successCount}, Failed: ${errorCount}`;

    if (successCount > 0) {
      addResult(true, `\n--- ${successCount} bookmark(s) deleted and will sync to your account ---`);
    }

    // Re-enable buttons
    loadFileBtn.disabled = false;
    pasteBtn.disabled = false;
    clearBtn.disabled = false;
    bookmarkIdsInput.disabled = false;
    deleteBtn.disabled = false;

    // Clear the input if all successful
    if (errorCount === 0) {
      bookmarkIdsInput.value = '';
      updateCount();
    }
  });

  function getIds() {
    return bookmarkIdsInput.value
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.length > 0 && !line.startsWith('#'));
  }

  function updateCount() {
    const ids = getIds();
    countDisplay.textContent = `${ids.length} bookmark ID(s) loaded`;
    deleteBtn.disabled = ids.length === 0;
  }

  function addResult(success, message) {
    const div = document.createElement('div');
    div.className = success ? 'success' : 'error';
    div.textContent = (success ? '✓ ' : '✗ ') + message;
    resultsDiv.appendChild(div);
    resultsDiv.scrollTop = resultsDiv.scrollHeight;
  }

  // Initial count
  updateCount();
});
