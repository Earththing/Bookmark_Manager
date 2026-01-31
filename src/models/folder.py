"""Folder model for hierarchical bookmark organization."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import sqlite3


@dataclass
class Folder:
    """Represents a folder/collection for organizing bookmarks."""

    folder_id: Optional[int] = None
    name: str = ""
    parent_folder_id: Optional[int] = None
    browser_profile_id: Optional[int] = None
    browser_folder_id: Optional[str] = None  # Original ID from browser
    browser_folder_path: Optional[str] = None  # Path like "Bookmarks Bar/Work"
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Folder":
        """Create a Folder from a database row."""
        return cls(
            folder_id=row["folder_id"],
            name=row["name"],
            parent_folder_id=row["parent_folder_id"],
            browser_profile_id=row["browser_profile_id"],
            browser_folder_id=row["browser_folder_id"],
            browser_folder_path=row["browser_folder_path"],
            position=row["position"],
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None,
            updated_at=datetime.fromisoformat(row["updated_at"])
            if row["updated_at"]
            else None,
        )

    def save(self, db) -> "Folder":
        """Save the folder to the database."""
        if self.folder_id is None:
            cursor = db.execute(
                """
                INSERT INTO folders
                (name, parent_folder_id, browser_profile_id, browser_folder_id,
                 browser_folder_path, position)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self.name,
                    self.parent_folder_id,
                    self.browser_profile_id,
                    self.browser_folder_id,
                    self.browser_folder_path,
                    self.position,
                ),
            )
            db.commit()
            self.folder_id = cursor.lastrowid
        else:
            db.execute(
                """
                UPDATE folders
                SET name = ?, parent_folder_id = ?, browser_profile_id = ?,
                    browser_folder_id = ?, browser_folder_path = ?,
                    position = ?, updated_at = CURRENT_TIMESTAMP
                WHERE folder_id = ?
                """,
                (
                    self.name,
                    self.parent_folder_id,
                    self.browser_profile_id,
                    self.browser_folder_id,
                    self.browser_folder_path,
                    self.position,
                    self.folder_id,
                ),
            )
            db.commit()
        return self

    @classmethod
    def find_by_id(cls, db, folder_id: int) -> Optional["Folder"]:
        """Find a folder by its database ID."""
        cursor = db.execute("SELECT * FROM folders WHERE folder_id = ?", (folder_id,))
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def find_by_browser_id(
        cls, db, browser_profile_id: int, browser_folder_id: str
    ) -> Optional["Folder"]:
        """Find a folder by its browser profile and browser folder ID."""
        cursor = db.execute(
            """
            SELECT * FROM folders
            WHERE browser_profile_id = ? AND browser_folder_id = ?
            """,
            (browser_profile_id, browser_folder_id),
        )
        row = cursor.fetchone()
        return cls.from_row(row) if row else None

    @classmethod
    def get_root_folders(cls, db) -> List["Folder"]:
        """Get all root-level folders (no parent)."""
        cursor = db.execute(
            "SELECT * FROM folders WHERE parent_folder_id IS NULL ORDER BY position, name"
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_children(cls, db, parent_folder_id: int) -> List["Folder"]:
        """Get all child folders of a parent folder."""
        cursor = db.execute(
            "SELECT * FROM folders WHERE parent_folder_id = ? ORDER BY position, name",
            (parent_folder_id,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    @classmethod
    def get_by_profile(cls, db, browser_profile_id: int) -> List["Folder"]:
        """Get all folders from a specific browser profile."""
        cursor = db.execute(
            """
            SELECT * FROM folders
            WHERE browser_profile_id = ?
            ORDER BY browser_folder_path, position
            """,
            (browser_profile_id,),
        )
        return [cls.from_row(row) for row in cursor.fetchall()]

    def get_full_path(self, db) -> str:
        """Get the full path of this folder including all parent names."""
        path_parts = [self.name]
        current = self

        while current.parent_folder_id is not None:
            parent = Folder.find_by_id(db, current.parent_folder_id)
            if parent:
                path_parts.insert(0, parent.name)
                current = parent
            else:
                break

        return " / ".join(path_parts)

    def delete(self, db):
        """Delete this folder from the database (cascades to children)."""
        if self.folder_id:
            db.execute("DELETE FROM folders WHERE folder_id = ?", (self.folder_id,))
            db.commit()
            self.folder_id = None

    @classmethod
    def delete_by_profile(cls, db, browser_profile_id: int):
        """Delete all folders from a specific browser profile."""
        db.execute(
            "DELETE FROM folders WHERE browser_profile_id = ?",
            (browser_profile_id,),
        )
        db.commit()
