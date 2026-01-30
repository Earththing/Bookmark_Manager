"""Browser profile model for tracking synced browser profiles."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import sqlite3


@dataclass
class BrowserProfile:
    """Represents a browser profile that can be synced."""

    id: Optional[int] = None
    browser_name: str = ""  # e.g., "Chrome", "Edge"
    profile_id: str = ""  # e.g., "Default", "Profile 1"
    profile_name: Optional[str] = None  # User-friendly name from preferences
    profile_path: str = ""  # Full path to profile directory
    last_synced_at: Optional[datetime] = None
    sync_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BrowserProfile":
        """Create a BrowserProfile from a database row."""
        return cls(
            id=row["id"],
            browser_name=row["browser_name"],
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            profile_path=row["profile_path"],
            last_synced_at=datetime.fromisoformat(row["last_synced_at"])
            if row["last_synced_at"]
            else None,
            sync_enabled=bool(row["sync_enabled"]),
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None,
            updated_at=datetime.fromisoformat(row["updated_at"])
            if row["updated_at"]
            else None,
        )

    def save(self, db) -> "BrowserProfile":
        """Save the profile to the database."""
        if self.id is None:
            cursor = db.execute(
                """
                INSERT INTO browser_profiles
                (browser_name, profile_id, profile_name, profile_path, sync_enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.browser_name,
                    self.profile_id,
                    self.profile_name,
                    self.profile_path,
                    1 if self.sync_enabled else 0,
                ),
            )
            db.commit()
            self.id = cursor.lastrowid
        else:
            db.execute(
                """
                UPDATE browser_profiles
                SET browser_name = ?, profile_id = ?, profile_name = ?,
                    profile_path = ?, sync_enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    self.browser_name,
                    self.profile_id,
                    self.profile_name,
                    self.profile_path,
                    1 if self.sync_enabled else 0,
                    self.id,
                ),
            )
            db.commit()
        return self

    def update_last_synced(self, db):
        """Update the last_synced_at timestamp."""
        if self.id:
            db.execute(
                """
                UPDATE browser_profiles
                SET last_synced_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self.id,),
            )
            db.commit()
            self.last_synced_at = datetime.now()

    @classmethod
    def find_by_id(cls, db, profile_id: int) -> Optional["BrowserProfile"]:
        """Find a profile by its database ID."""
        cursor = db.execute(
            "SELECT * FROM browser_profiles WHERE id = ?", (profile_id,)
        )
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def find_by_browser_and_profile(
        cls, db, browser_name: str, profile_id: str
    ) -> Optional["BrowserProfile"]:
        """Find a profile by browser name and profile ID."""
        cursor = db.execute(
            "SELECT * FROM browser_profiles WHERE browser_name = ? AND profile_id = ?",
            (browser_name, profile_id),
        )
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def get_all(cls, db) -> List["BrowserProfile"]:
        """Get all browser profiles."""
        cursor = db.execute("SELECT * FROM browser_profiles ORDER BY browser_name, profile_id")
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_enabled(cls, db) -> List["BrowserProfile"]:
        """Get all enabled browser profiles."""
        cursor = db.execute(
            "SELECT * FROM browser_profiles WHERE sync_enabled = 1 ORDER BY browser_name, profile_id"
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    def get_bookmarks_path(self) -> Path:
        """Get the path to the Bookmarks file for this profile."""
        return Path(self.profile_path) / "Bookmarks"

    def delete(self, db):
        """Delete this profile from the database."""
        if self.id:
            db.execute("DELETE FROM browser_profiles WHERE id = ?", (self.id,))
            db.commit()
            self.id = None
