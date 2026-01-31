"""SQLite database connection and setup."""

import sqlite3
from pathlib import Path
from typing import Optional
import os


class Database:
    """Manages SQLite database connection and schema."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            db_path: Path to the database file. If None, uses default location
                     in user's home directory.
        """
        if db_path is None:
            # Default to user's home directory
            app_data = Path.home() / ".bookmark_manager"
            app_data.mkdir(exist_ok=True)
            db_path = app_data / "bookmarks.db"

        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Establish database connection."""
        if self.connection is None:
            self.connection = sqlite3.connect(str(self.db_path))
            self.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self.connection.execute("PRAGMA foreign_keys = ON")
        return self.connection

    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def initialize_schema(self):
        """Create database tables if they don't exist."""
        conn = self.connect()
        cursor = conn.cursor()

        # Browser profiles table - tracks each browser profile we sync with
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS browser_profiles (
                browser_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                browser_name TEXT NOT NULL,
                browser_profile_name TEXT NOT NULL,
                profile_display_name TEXT,
                profile_path TEXT NOT NULL,
                last_synced_at TIMESTAMP,
                sync_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(browser_name, browser_profile_name)
            )
        """)

        # Folders table - hierarchical folder structure
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                folder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_folder_id INTEGER,
                browser_profile_id INTEGER,
                browser_folder_id TEXT,
                browser_folder_path TEXT,
                position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE,
                FOREIGN KEY (browser_profile_id) REFERENCES browser_profiles(browser_profile_id) ON DELETE SET NULL
            )
        """)

        # Bookmarks table - the main bookmark entries
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                bookmark_id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                description TEXT,
                notes TEXT,
                favicon_url TEXT,
                folder_id INTEGER,
                browser_profile_id INTEGER,
                browser_bookmark_id TEXT,
                browser_added_at TIMESTAMP,
                position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE SET NULL,
                FOREIGN KEY (browser_profile_id) REFERENCES browser_profiles(browser_profile_id) ON DELETE SET NULL
            )
        """)

        # Tags table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Bookmark-tags junction table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmark_tags (
                bookmark_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (bookmark_id, tag_id),
                FOREIGN KEY (bookmark_id) REFERENCES bookmarks(bookmark_id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
            )
        """)

        # Sync metadata table - tracks sync operations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                sync_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                browser_profile_id INTEGER NOT NULL,
                sync_type TEXT NOT NULL,
                bookmarks_added INTEGER DEFAULT 0,
                bookmarks_updated INTEGER DEFAULT 0,
                bookmarks_deleted INTEGER DEFAULT 0,
                folders_added INTEGER DEFAULT 0,
                folders_updated INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (browser_profile_id) REFERENCES browser_profiles(browser_profile_id) ON DELETE CASCADE
            )
        """)

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_url ON bookmarks(url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_folder ON bookmarks(folder_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_profile ON bookmarks(browser_profile_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_folder_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_folders_profile ON folders(browser_profile_id)")

        # Full-text search virtual table for bookmarks
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS bookmarks_fts USING fts5(
                title,
                url,
                description,
                notes,
                content=bookmarks,
                content_rowid=bookmark_id
            )
        """)

        # Triggers to keep FTS in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS bookmarks_ai AFTER INSERT ON bookmarks BEGIN
                INSERT INTO bookmarks_fts(rowid, title, url, description, notes)
                VALUES (new.bookmark_id, new.title, new.url, new.description, new.notes);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS bookmarks_ad AFTER DELETE ON bookmarks BEGIN
                INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, description, notes)
                VALUES ('delete', old.bookmark_id, old.title, old.url, old.description, old.notes);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS bookmarks_au AFTER UPDATE ON bookmarks BEGIN
                INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, description, notes)
                VALUES ('delete', old.bookmark_id, old.title, old.url, old.description, old.notes);
                INSERT INTO bookmarks_fts(rowid, title, url, description, notes)
                VALUES (new.bookmark_id, new.title, new.url, new.description, new.notes);
            END
        """)

        # View to see bookmarks with their location info for verification
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_bookmarks_with_location AS
            SELECT
                b.bookmark_id,
                b.title AS bookmark_title,
                b.url,
                b.browser_added_at,
                f.name AS folder_name,
                f.browser_folder_path AS folder_path,
                bp.browser_name,
                bp.browser_profile_name,
                bp.profile_display_name,
                bp.profile_path,
                -- Construct the full path to the Bookmarks file
                bp.profile_path || '\\Bookmarks' AS bookmarks_file_path
            FROM bookmarks b
            LEFT JOIN folders f ON b.folder_id = f.folder_id
            LEFT JOIN browser_profiles bp ON b.browser_profile_id = bp.browser_profile_id
            ORDER BY bp.browser_name, bp.browser_profile_name, f.browser_folder_path, b.position
        """)

        # Dead links table - stores results of dead link checks
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dead_links (
                dead_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bookmark_id INTEGER NOT NULL,
                check_run_id TEXT NOT NULL,
                status_code INTEGER,
                error_message TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bookmark_id) REFERENCES bookmarks(bookmark_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_links_bookmark ON dead_links(bookmark_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dead_links_run ON dead_links(check_run_id)")

        # Duplicate groups table - stores duplicate detection results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                duplicate_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_run_id TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                match_type TEXT NOT NULL,
                similarity REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_duplicate_groups_run ON duplicate_groups(check_run_id)")

        # Duplicate group members - links bookmarks to their duplicate groups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_group_members (
                duplicate_group_id INTEGER NOT NULL,
                bookmark_id INTEGER NOT NULL,
                PRIMARY KEY (duplicate_group_id, bookmark_id),
                FOREIGN KEY (duplicate_group_id) REFERENCES duplicate_groups(duplicate_group_id) ON DELETE CASCADE,
                FOREIGN KEY (bookmark_id) REFERENCES bookmarks(bookmark_id) ON DELETE CASCADE
            )
        """)

        # View for dead links with bookmark details
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_dead_links AS
            SELECT
                dl.dead_link_id,
                dl.check_run_id,
                dl.status_code,
                dl.error_message,
                dl.checked_at,
                b.bookmark_id,
                b.title,
                b.url,
                f.name AS folder_name,
                bp.browser_name,
                bp.profile_display_name
            FROM dead_links dl
            JOIN bookmarks b ON dl.bookmark_id = b.bookmark_id
            LEFT JOIN folders f ON b.folder_id = f.folder_id
            LEFT JOIN browser_profiles bp ON b.browser_profile_id = bp.browser_profile_id
            ORDER BY dl.checked_at DESC, b.title
        """)

        # View for exact duplicates with bookmark details
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_duplicates_exact AS
            SELECT
                dg.duplicate_group_id,
                dg.check_run_id,
                dg.normalized_url,
                dg.created_at AS detected_at,
                b.bookmark_id,
                b.title,
                b.url,
                f.name AS folder_name,
                bp.browser_name,
                bp.profile_display_name,
                (SELECT COUNT(*) FROM duplicate_group_members dgm2
                 WHERE dgm2.duplicate_group_id = dg.duplicate_group_id) AS group_size
            FROM duplicate_groups dg
            JOIN duplicate_group_members dgm ON dg.duplicate_group_id = dgm.duplicate_group_id
            JOIN bookmarks b ON dgm.bookmark_id = b.bookmark_id
            LEFT JOIN folders f ON b.folder_id = f.folder_id
            LEFT JOIN browser_profiles bp ON b.browser_profile_id = bp.browser_profile_id
            WHERE dg.match_type = 'exact'
            ORDER BY dg.duplicate_group_id, b.title
        """)

        # View for similar duplicates with bookmark details
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS vw_duplicates_similar AS
            SELECT
                dg.duplicate_group_id,
                dg.check_run_id,
                dg.normalized_url,
                dg.similarity,
                dg.created_at AS detected_at,
                b.bookmark_id,
                b.title,
                b.url,
                f.name AS folder_name,
                bp.browser_name,
                bp.profile_display_name,
                (SELECT COUNT(*) FROM duplicate_group_members dgm2
                 WHERE dgm2.duplicate_group_id = dg.duplicate_group_id) AS group_size
            FROM duplicate_groups dg
            JOIN duplicate_group_members dgm ON dg.duplicate_group_id = dgm.duplicate_group_id
            JOIN bookmarks b ON dgm.bookmark_id = b.bookmark_id
            LEFT JOIN folders f ON b.folder_id = f.folder_id
            LEFT JOIN browser_profiles bp ON b.browser_profile_id = bp.browser_profile_id
            WHERE dg.match_type = 'similar'
            ORDER BY dg.similarity DESC, dg.duplicate_group_id, b.title
        """)

        conn.commit()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL query."""
        conn = self.connect()
        return conn.execute(query, params)

    def executemany(self, query: str, params_list: list) -> sqlite3.Cursor:
        """Execute a SQL query with multiple parameter sets."""
        conn = self.connect()
        return conn.executemany(query, params_list)

    def commit(self):
        """Commit current transaction."""
        if self.connection:
            self.connection.commit()

    def rollback(self):
        """Rollback current transaction."""
        if self.connection:
            self.connection.rollback()


# Global database instance
_database: Optional[Database] = None


def get_database(db_path: Optional[Path] = None) -> Database:
    """Get or create the global database instance."""
    global _database
    if _database is None:
        _database = Database(db_path)
        _database.initialize_schema()
    return _database


def reset_database():
    """Reset the global database instance (mainly for testing)."""
    global _database
    if _database:
        _database.close()
    _database = None
