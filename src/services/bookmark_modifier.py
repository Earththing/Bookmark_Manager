"""Service to modify browser bookmark files."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ModificationResult:
    """Result of a bookmark modification operation."""
    browser_name: str
    profile_name: str
    profile_path: Path
    bookmarks_deleted: int = 0
    backup_path: Optional[Path] = None
    success: bool = False
    error_message: Optional[str] = None


@dataclass
class BookmarkToDelete:
    """A bookmark that should be deleted from a browser."""
    bookmark_id: int  # Our database ID
    browser_bookmark_id: str  # The browser's ID for this bookmark
    browser_name: str
    profile_path: Path
    profile_name: str
    url: str
    title: str
    reason: str  # "dead_link", "exact_duplicate", "similar_duplicate"


class BookmarkModifierService:
    """Service to modify browser bookmark files."""

    def __init__(self):
        self.backup_dir = Path.home() / ".bookmark_manager" / "browser_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, profile_path: Path, browser_name: str, profile_name: str) -> Path:
        """Create a backup of the browser's Bookmarks file.

        Args:
            profile_path: Path to the browser profile directory
            browser_name: Name of the browser
            profile_name: Name of the profile

        Returns:
            Path to the backup file
        """
        bookmarks_file = profile_path / "Bookmarks"
        if not bookmarks_file.exists():
            raise FileNotFoundError(f"Bookmarks file not found: {bookmarks_file}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_profile = profile_name.replace(" ", "_").replace("/", "_")
        backup_name = f"{browser_name}_{safe_profile}_Bookmarks_{timestamp}.json"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(bookmarks_file, backup_path)
        return backup_path

    def delete_bookmarks(
        self,
        bookmarks_to_delete: List[BookmarkToDelete],
        create_backup: bool = True
    ) -> List[ModificationResult]:
        """Delete bookmarks from browser files.

        Args:
            bookmarks_to_delete: List of bookmarks to delete
            create_backup: Whether to create backups before modifying

        Returns:
            List of ModificationResult for each profile modified
        """
        # Group bookmarks by profile
        by_profile: Dict[Tuple[str, str], List[BookmarkToDelete]] = {}
        for bookmark in bookmarks_to_delete:
            key = (str(bookmark.profile_path), bookmark.browser_name)
            if key not in by_profile:
                by_profile[key] = []
            by_profile[key].append(bookmark)

        results = []

        for (profile_path_str, browser_name), profile_bookmarks in by_profile.items():
            profile_path = Path(profile_path_str)
            profile_name = profile_bookmarks[0].profile_name

            result = ModificationResult(
                browser_name=browser_name,
                profile_name=profile_name,
                profile_path=profile_path
            )

            try:
                # Create backup if requested
                if create_backup:
                    result.backup_path = self.create_backup(
                        profile_path, browser_name, profile_name
                    )

                # Get the browser bookmark IDs to delete (convert to strings for JSON comparison)
                ids_to_delete = {str(b.browser_bookmark_id) for b in profile_bookmarks}

                # Verify the bookmarks file exists
                bookmarks_file = profile_path / "Bookmarks"
                if not bookmarks_file.exists():
                    result.success = False
                    result.error_message = f"Bookmarks file not found: {bookmarks_file}"
                    results.append(result)
                    continue

                # Load, modify, and save the bookmarks file
                deleted_count = self._modify_bookmarks_file(
                    profile_path, ids_to_delete
                )

                result.bookmarks_deleted = deleted_count
                result.success = True

                # Add info if no bookmarks were deleted (IDs may not match)
                if deleted_count == 0 and len(ids_to_delete) > 0:
                    result.error_message = f"Warning: Requested to delete {len(ids_to_delete)} bookmarks but none were found in file. IDs may have changed."

            except Exception as e:
                result.success = False
                result.error_message = str(e)

            results.append(result)

        return results

    def _modify_bookmarks_file(
        self,
        profile_path: Path,
        ids_to_delete: Set[str]
    ) -> int:
        """Modify the bookmarks file to remove specified bookmarks.

        Args:
            profile_path: Path to the browser profile
            ids_to_delete: Set of browser bookmark IDs to delete

        Returns:
            Number of bookmarks deleted
        """
        bookmarks_file = profile_path / "Bookmarks"

        # Read the current bookmarks
        with open(bookmarks_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Track how many we delete
        deleted_count = 0

        # Process each root folder
        if 'roots' in data:
            for root_name in list(data['roots'].keys()):
                root = data['roots'][root_name]
                if isinstance(root, dict) and 'children' in root:
                    deleted_count += self._delete_from_folder(
                        root, ids_to_delete
                    )

        if deleted_count > 0:
            # Write the modified bookmarks back
            with open(bookmarks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=3)

        return deleted_count

    def _delete_from_folder(
        self,
        folder: Dict,
        ids_to_delete: Set[str]
    ) -> int:
        """Recursively delete bookmarks from a folder.

        Args:
            folder: The folder dictionary
            ids_to_delete: Set of bookmark IDs to delete

        Returns:
            Number of bookmarks deleted
        """
        if 'children' not in folder:
            return 0

        deleted_count = 0
        new_children = []

        for child in folder['children']:
            # Get ID and convert to string for comparison (JSON may store as int or str)
            child_id = str(child.get('id', ''))
            child_type = child.get('type', '')

            if child_type == 'url' and child_id in ids_to_delete:
                # Skip this bookmark (delete it)
                deleted_count += 1
            elif child_type == 'folder':
                # Recursively process subfolders
                deleted_count += self._delete_from_folder(child, ids_to_delete)
                new_children.append(child)
            else:
                # Keep this item
                new_children.append(child)

        folder['children'] = new_children
        return deleted_count

    def get_affected_browsers(
        self,
        bookmarks_to_delete: List[BookmarkToDelete]
    ) -> Set[str]:
        """Get the set of browser names that will be affected.

        Args:
            bookmarks_to_delete: List of bookmarks to delete

        Returns:
            Set of browser names (e.g., {"Chrome", "Edge"})
        """
        return {b.browser_name for b in bookmarks_to_delete}

    def get_deletion_summary(
        self,
        bookmarks_to_delete: List[BookmarkToDelete]
    ) -> Dict[str, Dict[str, int]]:
        """Get a summary of deletions by browser and profile.

        Args:
            bookmarks_to_delete: List of bookmarks to delete

        Returns:
            Dict like {"Chrome": {"Profile 1": 5, "Profile 2": 3}, "Edge": {...}}
        """
        summary: Dict[str, Dict[str, int]] = {}

        for bookmark in bookmarks_to_delete:
            browser = bookmark.browser_name
            profile = bookmark.profile_name

            if browser not in summary:
                summary[browser] = {}
            if profile not in summary[browser]:
                summary[browser][profile] = 0

            summary[browser][profile] += 1

        return summary
