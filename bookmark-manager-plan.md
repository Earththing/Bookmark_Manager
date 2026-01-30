# Bookmark Manager Application - Development Plan

## Project Overview
A single-user desktop bookmark manager application built with Python to help organize, search, and manage saved links efficiently. The application will be able to import bookmarks from browsers and write changes back to browser bookmark files.

## Key Requirements
- **Single User**: Local desktop application, no authentication needed
- **Desktop Focus**: Standalone application (not web-based initially)
- **Python-based**: Core application in Python with GUI framework
- **Browser Sync**: Two-way sync - import from and export to browser bookmark files
- **Multi-Profile Support**: Handle all profiles from Chrome and Edge (initially)
- **No Browser Extension**: Works with bookmark files directly, no extension needed
- **Theming**: Low priority, can be added later

---

## Section 1: Core Data Model & Storage

### Components:
- **Bookmark Structure**
  - URL (required)
  - Title
  - Description
  - Tags/Categories
  - Created/Modified timestamps
  - Favicon/Thumbnail
  - Notes/Annotations
  - **Source tracking**
    - Browser name (Chrome, Edge, etc.)
    - Profile name/ID
    - Original folder path in browser
    - Last synced timestamp

- **Collections/Folders**
  - Hierarchical organization
  - Nested folder support
  - Folder metadata
  - **Browser profile mapping**
    - Track which folders came from which profile
    - Maintain browser folder structure

- **Storage Layer**
  - SQLite database (local, file-based, perfect for single-user)
  - Schema design
  - Data validation
  - Database file location in user's home directory
  - **Profile sync metadata table**
    - Track each browser profile
    - Last sync timestamps
    - Sync settings per profile

**Priority:** HIGH - Foundation for everything else

---

## Section 2: User Interface & Navigation

### Components:
- **Main Layout**
  - Sidebar for folders/collections
  - Main content area for bookmark list
  - Search bar
  - Add bookmark button

- **Bookmark Display**
  - List view
  - Grid view
  - Card view with previews

- **Navigation**
  - Folder tree navigation
  - Breadcrumbs
  - Quick access/favorites

**Priority:** HIGH - User's primary interaction point

---

## Section 3: Add & Edit Functionality

### Components:
- **Add Bookmark**
  - Manual URL entry
  - Form with all fields
  - Auto-fetch title and metadata
  - Quick add (minimal fields)

- **Edit Bookmark**
  - Inline editing
  - Modal/drawer edit form
  - Bulk edit capabilities

- **Import Functionality**
  - Chrome/Chromium bookmarks (JSON format)
  - Firefox bookmarks (JSON/JSONLZ4 format)
  - Safari bookmarks (plist format)
  - Browser bookmark HTML export
  - CSV import (generic)
  - Detect browser installation paths automatically

**Priority:** HIGH - Core functionality

---

## Section 4: Search & Filter System

### Components:
- **Search Features**
  - Full-text search
  - Search by title, URL, tags, notes
  - Search suggestions/autocomplete
  - Recent searches

- **Filtering**
  - Filter by tags
  - Filter by date range
  - Filter by folder
  - Combined filters

- **Advanced Search**
  - Boolean operators
  - Saved searches

**Priority:** MEDIUM - Essential for usability as collection grows

---

## Section 5: Tagging & Organization

### Components:
- **Tag System**
  - Create/edit/delete tags
  - Tag autocomplete
  - Tag colors/icons
  - Tag cloud visualization

- **Organization Tools**
  - Drag-and-drop to folders
  - Multi-select operations
  - Duplicate detection
  - Dead link detection

**Priority:** MEDIUM - Improves organization

---

## Section 6: Browser File Sync

### Components:
- **Browser Detection**
  - Auto-detect installed browsers (Chrome, Edge initially)
  - Locate bookmark file paths for each browser
  - **Multi-Profile Support**
    - Detect all profiles for each browser
    - List profile names (Default, Profile 1, Personal, Work, etc.)
    - Handle custom profile names
    - Track profile metadata (last used, size, bookmark count)
  - Future: Firefox, Safari, Brave support

- **Profile Management UI**
  - Display all detected browsers and their profiles
  - Select which profiles to sync
  - Profile-specific sync settings
  - Visual indication of active/inactive profiles
  - Show last sync time per profile

- **Two-Way Sync**
  - Read from browser bookmark files (per profile)
  - Write changes back to browser files (per profile)
  - Backup browser bookmarks before write
  - Merge strategies (replace, merge, selective)
  - Track bookmark source (which browser/profile)
  - Handle profile-specific folder structures

- **Sync Safety**
  - Browser must be closed for file writing
  - Detect if browser is running (any profile)
  - Validation before writing
  - Rollback capability per profile
  - Prevent data loss between profiles

**Priority:** HIGH - Core differentiator for the application

---

## Section 7: Export & Backup

### Components:
- **Export Options**
  - HTML format (browser-compatible)
  - JSON export
  - CSV export
  - Markdown export

- **Backup System**
  - Automatic backups
  - Manual backup creation
  - Restore functionality

**Priority:** MEDIUM - Data safety

---

## Section 8: Advanced Features

### Components:
- **Annotations & Notes**
  - Rich text notes
  - Highlights/excerpts
  - Screenshots

- **Sharing**
  - Public/private links
  - Share collections
  - Collaborative folders

- **Analytics**
  - Usage statistics
  - Most visited bookmarks
  - Tag statistics

**Priority:** LOW - Nice to have

---

## Section 9: Application Settings

### Components:
- **Settings**
  - Default browser selection
  - Auto-sync preferences
  - Default view preferences
  - Backup location
  - Import/export settings
  - Theme preferences (future)

- **Application Preferences**
  - Startup behavior
  - Database location
  - Keyboard shortcuts
  - Notification preferences

**Priority:** LOW - Can use defaults initially

---

## Section 10: Performance & Optimization

### Components:
- **Performance**
  - Lazy loading
  - Pagination
  - Caching strategy
  - Database indexing

- **Responsive Design**
  - Mobile optimization
  - Tablet layout
  - Desktop experience

**Priority:** MEDIUM - Important for good UX

---

## Suggested Development Order

1. **Phase 1 - MVP (Core Functionality)**
   - Section 1: Core Data Model & Storage (SQLite)
   - Section 2: User Interface & Navigation (basic PyQt/Tkinter)
   - Section 3: Add & Edit Functionality (basic forms)
   - Section 7: Export & Backup (basic HTML export)

2. **Phase 2 - Browser Integration**
   - Section 6: Browser File Sync (import from browsers)
   - Section 3: Import Functionality (complete)
   - Section 7: Export to browser format (write back)

3. **Phase 3 - Enhanced Features**
   - Section 4: Search & Filter System
   - Section 5: Tagging & Organization
   - Section 10: Performance & Optimization

4. **Phase 4 - Polish & Advanced Features**
   - Section 8: Advanced Features (notes, screenshots)
   - Section 9: Application Settings
   - Theme support (future)
   - Packaging for distribution

---

## Technical Stack Considerations

### Desktop GUI Framework (Python):
- **PyQt6/PySide6** (Recommended - Modern, powerful, cross-platform)
  - Rich widget library
  - Great documentation
  - Professional appearance
- **Tkinter** (Built-in, lightweight)
  - No external dependencies
  - Limited styling options
- **Kivy** (Mobile-ready if expansion planned)
- **wxPython** (Native look and feel)

### Database:
- **SQLite** (Chosen)
  - File-based, no server needed
  - Built into Python
  - Perfect for single-user
  - Supports full-text search

### Additional Python Libraries:
- **SQLAlchemy** - Database ORM
- **Pydantic** - Data validation
- **platformdirs** - Cross-platform config/data paths
- **psutil** - Process detection (check if browser running)
- **beautifulsoup4** - Parse HTML bookmark exports
- **requests** - Fetch favicon/metadata from URLs
- **python-magic** - File type detection

### Browser Bookmark Formats:
- Chrome/Edge: JSON files
  - Default profile: `User Data/Default/Bookmarks`
  - Named profiles: `User Data/Profile 1/Bookmarks`, `User Data/Profile 2/Bookmarks`, etc.
  - Custom profiles: `User Data/[ProfileName]/Bookmarks`
- Firefox: JSONLZ4 (compressed JSON)
- Safari: Binary plist format
- HTML: Universal export format

### Browser Profile Detection:
- **Chrome/Edge Profiles**:
  - Windows: `%LOCALAPPDATA%\Google\Chrome\User Data\` or `\Microsoft\Edge\User Data\`
  - macOS: `~/Library/Application Support/Google/Chrome/` or `~/Library/Application Support/Microsoft Edge/`
  - Linux: `~/.config/google-chrome/` or `~/.config/microsoft-edge/`
  - Profile discovery: Scan User Data folder for all Profile directories
  - Profile names: Parse from `Preferences` file in each profile folder

### Packaging:
- **PyInstaller** - Create standalone executables
- **cx_Freeze** - Alternative packaging
- **py2app** - macOS specific
- **Nuitka** - Python to C++ compilation

---

## Suggested Project Structure

```
bookmark-manager/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Application entry point
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite connection and setup
│   │   ├── bookmark.py         # Bookmark model
│   │   ├── folder.py           # Folder/collection model
│   │   └── browser_profile.py  # Browser profile tracking model
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # Main application window
│   │   ├── bookmark_list.py    # Bookmark display widgets
│   │   ├── edit_dialog.py      # Add/edit bookmark dialog
│   │   ├── search_bar.py       # Search interface
│   │   └── profile_manager.py  # Browser profile selection UI
│   ├── services/
│   │   ├── __init__.py
│   │   ├── browser_sync.py     # Browser file sync logic
│   │   ├── profile_detector.py # Detect browser profiles
│   │   ├── import_service.py   # Import from various formats
│   │   ├── export_service.py   # Export functionality
│   │   └── metadata_fetcher.py # Fetch URL metadata
│   └── utils/
│       ├── __init__.py
│       ├── browser_paths.py    # Detect browser locations
│       └── validators.py       # URL and data validation
├── tests/
│   ├── test_models.py
│   ├── test_browser_sync.py
│   ├── test_profile_detector.py
│   └── test_import.py
├── resources/
│   ├── icons/
│   └── default_bookmarks.json
├── requirements.txt
├── setup.py
└── README.md
```

---

## Next Steps

Which section would you like to start working on? I recommend:

1. **Start with Section 1 (Database Model)** - Create the SQLite schema and models
2. **Choose GUI Framework** - Decide between PyQt6, Tkinter, or another framework
3. **Start with Section 6 (Browser Sync)** - If you want to tackle the unique feature first
4. **Create project structure** - Set up the basic Python project skeleton

Let me know which approach you prefer, and we'll start building!
