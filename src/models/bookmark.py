"""Bookmark model for storing bookmark entries."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import sqlite3


@dataclass
class Bookmark:
    """Represents a bookmark entry."""

    bookmark_id: Optional[int] = None
    url: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    favicon_url: Optional[str] = None
    folder_id: Optional[int] = None
    browser_profile_id: Optional[int] = None
    browser_bookmark_id: Optional[str] = None  # Original ID from browser
    browser_added_at: Optional[datetime] = None
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Bookmark":
        """Create a Bookmark from a database row."""
        return cls(
            bookmark_id=row["bookmark_id"],
            url=row["url"],
            title=row["title"],
            description=row["description"],
            notes=row["notes"],
            favicon_url=row["favicon_url"],
            folder_id=row["folder_id"],
            browser_profile_id=row["browser_profile_id"],
            browser_bookmark_id=row["browser_bookmark_id"],
            browser_added_at=datetime.fromisoformat(row["browser_added_at"])
            if row["browser_added_at"]
            else None,
            position=row["position"],
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None,
            updated_at=datetime.fromisoformat(row["updated_at"])
            if row["updated_at"]
            else None,
        )

    def save(self, db) -> "Bookmark":
        """Save the bookmark to the database."""
        browser_added_str = (
            self.browser_added_at.isoformat() if self.browser_added_at else None
        )

        if self.bookmark_id is None:
            cursor = db.execute(
                """
                INSERT INTO bookmarks
                (url, title, description, notes, favicon_url, folder_id,
                 browser_profile_id, browser_bookmark_id, browser_added_at, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.url,
                    self.title,
                    self.description,
                    self.notes,
                    self.favicon_url,
                    self.folder_id,
                    self.browser_profile_id,
                    self.browser_bookmark_id,
                    browser_added_str,
                    self.position,
                ),
            )
            db.commit()
            self.bookmark_id = cursor.lastrowid
        else:
            db.execute(
                """
                UPDATE bookmarks
                SET url = ?, title = ?, description = ?, notes = ?,
                    favicon_url = ?, folder_id = ?, browser_profile_id = ?,
                    browser_bookmark_id = ?, browser_added_at = ?,
                    position = ?, updated_at = CURRENT_TIMESTAMP
                WHERE bookmark_id = ?
                """,
                (
                    self.url,
                    self.title,
                    self.description,
                    self.notes,
                    self.favicon_url,
                    self.folder_id,
                    self.browser_profile_id,
                    self.browser_bookmark_id,
                    browser_added_str,
                    self.position,
                    self.bookmark_id,
                ),
            )
            db.commit()
        return self

    @classmethod
    def find_by_id(cls, db, bookmark_id: int) -> Optional["Bookmark"]:
        """Find a bookmark by its database ID."""
        cursor = db.execute("SELECT * FROM bookmarks WHERE bookmark_id = ?", (bookmark_id,))
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def find_by_browser_id(
        cls, db, browser_profile_id: int, browser_bookmark_id: str
    ) -> Optional["Bookmark"]:
        """Find a bookmark by its browser profile and browser bookmark ID."""
        cursor = db.execute(
            """
            SELECT * FROM bookmarks
            WHERE browser_profile_id = ? AND browser_bookmark_id = ?
            """,
            (browser_profile_id, browser_bookmark_id),
        )
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def find_by_url(cls, db, url: str) -> List["Bookmark"]:
        """Find all bookmarks with a specific URL."""
        cursor = db.execute(
            "SELECT * FROM bookmarks WHERE url = ? ORDER BY created_at",
            (url,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_all(cls, db) -> List["Bookmark"]:
        """Get all bookmarks."""
        cursor = db.execute("SELECT * FROM bookmarks ORDER BY position, title")
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_by_folder(cls, db, folder_id: int) -> List["Bookmark"]:
        """Get all bookmarks in a specific folder."""
        cursor = db.execute(
            "SELECT * FROM bookmarks WHERE folder_id = ? ORDER BY position, title",
            (folder_id,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_by_profile(cls, db, browser_profile_id: int) -> List["Bookmark"]:
        """Get all bookmarks from a specific browser profile."""
        cursor = db.execute(
            """
            SELECT * FROM bookmarks
            WHERE browser_profile_id = ?
            ORDER BY folder_id, position, title
            """,
            (browser_profile_id,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_unfiled(cls, db) -> List["Bookmark"]:
        """Get all bookmarks not in any folder."""
        cursor = db.execute(
            "SELECT * FROM bookmarks WHERE folder_id IS NULL ORDER BY position, title"
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def search(cls, db, query: str) -> List["Bookmark"]:
        """Search bookmarks using full-text search."""
        cursor = db.execute(
            """
            SELECT b.* FROM bookmarks b
            JOIN bookmarks_fts fts ON b.bookmark_id = fts.rowid
            WHERE bookmarks_fts MATCH ?
            ORDER BY rank
            """,
            (query,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def count(cls, db) -> int:
        """Get the total number of bookmarks."""
        cursor = db.execute("SELECT COUNT(*) as count FROM bookmarks")
        row = cursor.fetchone()
        return row["count"] if row else 0

    @classmethod
    def count_by_profile(cls, db, browser_profile_id: int) -> int:
        """Get the number of bookmarks from a specific profile."""
        cursor = db.execute(
            "SELECT COUNT(*) as count FROM bookmarks WHERE browser_profile_id = ?",
            (browser_profile_id,),
        )
        row = cursor.fetchone()
        return row["count"] if row else 0

    def delete(self, db):
        """Delete this bookmark from the database."""
        if self.bookmark_id:
            db.execute("DELETE FROM bookmarks WHERE bookmark_id = ?", (self.bookmark_id,))
            db.commit()
            self.bookmark_id = None

    @classmethod
    def delete_by_profile(cls, db, browser_profile_id: int):
        """Delete all bookmarks from a specific browser profile."""
        db.execute(
            "DELETE FROM bookmarks WHERE browser_profile_id = ?",
            (browser_profile_id,),
        )
        db.commit()
