# Bookmark Manager

A **desktop GUI application** (built with PyQt6) to organize and manage bookmarks imported from Chrome and Edge browsers.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-GUI-green.svg)
![SQLite](https://img.shields.io/badge/SQLite-Database-orange.svg)

## Features

- **Multi-Browser Support**: Import bookmarks from Chrome and Edge browsers
- **Multi-Profile Support**: Detects and imports from all browser profiles
- **Full-Text Search**: Search bookmarks by title, URL, or notes using SQLite FTS5
- **Folder Navigation**: Browse bookmarks by their original folder structure
- **Dead Link Detection**: Check for broken links with parallel URL checking
- **Duplicate Detection**: Find exact and similar duplicate bookmarks
- **Page Thumbnails**: Generate preview thumbnails for bookmarks (requires Playwright)
- **Delete from Browsers**: Remove dead links and duplicates from browser bookmark files
- **Database Backup**: Create timestamped backups before operations
- **Refresh All**: One-click backup, import, duplicate check, and dead link check

## Screenshots

*Coming soon*

## Installation

### Requirements

- Python 3.10+
- PyQt6
- psutil (for browser process detection)
- Playwright (optional, for page thumbnails)

### Setup

```bash
# Clone the repository
git clone https://github.com/Earththing/Bookmark_Manager.git
cd Bookmark_Manager

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required dependencies
pip install PyQt6 psutil

# Install optional dependencies for page thumbnails
pip install playwright
playwright install chromium
```

### Playwright Setup (for Thumbnails)

To enable page thumbnail generation, install Playwright:

```bash
pip install playwright
playwright install chromium
```

This downloads a headless Chromium browser (~150MB) used to capture page screenshots.
Without Playwright, thumbnail features will show placeholder images.

## Usage

### Running the GUI Application

From the project root:
```bash
python -m src.gui
```

This launches the graphical user interface where you can browse, search, and manage your bookmarks.

### Running the CLI (Command Line)

For a command-line import (useful for scripting):
```bash
python -m src.main
```

### First Run

1. Click **"Refresh All..."** button or go to **File > Refresh All...**
2. Keep all options checked and click **Start**
3. The application will:
   - Backup any existing database
   - Create a fresh database
   - Import all bookmarks from detected browser profiles
   - Find duplicate bookmarks
   - Check for dead links

### Individual Operations

- **File > Import from Browsers...** (Ctrl+I) - Import bookmarks only
- **File > Check Dead Links...** (Ctrl+D) - Check for broken links
- **File > Find Duplicates...** (Ctrl+U) - Find duplicate bookmarks
- **File > Generate Thumbnails...** (Ctrl+T) - Generate page preview thumbnails
- **File > Delete from Browsers...** (Ctrl+Shift+D) - Remove bookmarks from browser files
- **F5** - Refresh the view

### Browsing Bookmarks

- Use the folder tree on the left to navigate
- Click "All Bookmarks" to see everything
- Use the search bar to find specific bookmarks
- Double-click a bookmark to open it in your browser

### Understanding the Columns

| Column | Description |
|--------|-------------|
| Title | Bookmark title |
| URL | The bookmark URL |
| Folder | Original folder name |
| Browser/Profile | Source browser and profile |
| Dead | Red "X" if link is dead |
| Exact Dup | Number of exact duplicates |
| Similar | Number of similar URLs |

## Data Storage

The application stores data in the following locations:

- **Database**: `~/.bookmark_manager/bookmarks.db` - SQLite database with bookmarks
- **Thumbnails**: `~/.bookmark_manager/thumbnails/` - Cached page screenshots
- **Backups**: `~/.bookmark_manager/browser_backups/` - Browser bookmark file backups

### Database Views

For advanced users, the following views are available:

- `vw_bookmarks_with_location` - All bookmarks with folder and profile info
- `vw_dead_links` - Dead links with bookmark details
- `vw_duplicates_exact` - Exact duplicate groups
- `vw_duplicates_similar` - Similar URL groups

## Project Structure

```
Bookmark_Manager/
├── src/
│   ├── main.py                 # Application entry point
│   ├── models/
│   │   ├── database.py         # SQLite database setup
│   │   ├── bookmark.py         # Bookmark model
│   │   ├── folder.py           # Folder model
│   │   └── browser_profile.py  # Browser profile model
│   ├── services/
│   │   ├── profile_detector.py # Browser profile detection
│   │   ├── bookmark_parser.py  # Chromium bookmark file parser
│   │   └── import_service.py   # Import orchestration
│   ├── ui/
│   │   ├── main_window.py      # Main application window
│   │   ├── import_dialog.py    # Import progress dialog
│   │   ├── dead_link_dialog.py # Dead link checker
│   │   ├── duplicate_dialog.py # Duplicate finder
│   │   └── refresh_all_dialog.py # Refresh all operations
│   └── utils/
│       └── browser_paths.py    # Browser path utilities
├── README.md
└── .gitignore
```

## How It Works

### Browser Detection

The application automatically detects Chrome and Edge profiles by looking in standard locations:

- **Windows**:
  - Chrome: `%LOCALAPPDATA%\Google\Chrome\User Data\`
  - Edge: `%LOCALAPPDATA%\Microsoft\Edge\User Data\`

- **macOS**:
  - Chrome: `~/Library/Application Support/Google/Chrome/`
  - Edge: `~/Library/Application Support/Microsoft Edge/`

- **Linux**:
  - Chrome: `~/.config/google-chrome/`
  - Edge: `~/.config/microsoft-edge/`

### Duplicate Detection

**Exact Duplicates**: URLs are normalized before comparison:
- Lowercases domain
- Removes `www.` prefix
- Removes trailing slashes
- Sorts query parameters
- Strips tracking parameters (utm_*, fbclid, gclid, etc.)

**Similar URLs**: Uses fuzzy matching to find URLs that are similar but not identical (configurable threshold, default 85%).

### Dead Link Detection

- Uses HEAD requests for efficiency (falls back to GET if needed)
- Parallel checking with configurable number of threads (default 10)
- Only checks each unique URL once (duplicates share results)
- Considers 4xx and 5xx status codes as dead

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- Uses SQLite with FTS5 for full-text search
