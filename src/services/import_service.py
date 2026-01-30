"""Service to import bookmarks from browsers into the database."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..models.database import Database
from ..models.browser_profile import BrowserProfile
from ..models.folder import Folder
from ..models.bookmark import Bookmark
from .profile_detector import ProfileDetector, DetectedProfile
from .bookmark_parser import BookmarkParser, ParsedBookmarksData


@dataclass
class ImportResult:
    """Result of an import operation."""

    profile: BrowserProfile
    bookmarks_added: int = 0
    bookmarks_updated: int = 0
    folders_added: int = 0
    folders_updated: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class ImportService:
    """Imports bookmarks from browser profiles into the database."""

    def __init__(self, db: Database):
        self.db = db
        self.profile_detector = ProfileDetector()
        self.bookmark_parser = BookmarkParser()

    def detect_profiles(self) -> List[DetectedProfile]:
        """Detect all available browser profiles.

        Returns:
            List of detected profiles
        """
        return self.profile_detector.detect_all_profiles()

    def import_profile(
        self, detected_profile: DetectedProfile, replace_existing: bool = False
    ) -> ImportResult:
        """Import bookmarks from a detected browser profile.

        Args:
            detected_profile: The profile to import from
            replace_existing: If True, delete existing bookmarks from this profile
                            before importing. If False, update existing and add new.

        Returns:
            ImportResult with statistics about the import
        """
        # Get or create the browser profile in the database
        db_profile = BrowserProfile.find_by_browser_and_profile(
            self.db, detected_profile.browser_name, detected_profile.profile_id
        )

        if db_profile is None:
            db_profile = BrowserProfile(
                browser_name=detected_profile.browser_name,
                profile_id=detected_profile.profile_id,
                profile_name=detected_profile.profile_name,
                profile_path=str(detected_profile.profile_path),
            )
            db_profile.save(self.db)

        result = ImportResult(profile=db_profile)

        # If replacing, delete existing data from this profile
        if replace_existing:
            Bookmark.delete_by_profile(self.db, db_profile.id)
            Folder.delete_by_profile(self.db, db_profile.id)

        # Parse the bookmarks file
        bookmarks_path = detected_profile.profile_path / "Bookmarks"
        if not bookmarks_path.exists():
            result.errors.append(f"Bookmarks file not found: {bookmarks_path}")
            return result

        try:
            parsed_data = self.bookmark_parser.parse_file(bookmarks_path)
        except Exception as e:
            result.errors.append(f"Error parsing bookmarks file: {e}")
            return result

        # Import folders first (need their IDs for bookmarks)
        folder_id_map = self._import_folders(db_profile, parsed_data, result)

        # Import bookmarks
        self._import_bookmarks(db_profile, parsed_data, folder_id_map, result)

        # Update last synced timestamp
        db_profile.update_last_synced(self.db)

        return result

    def _import_folders(
        self,
        db_profile: BrowserProfile,
        parsed_data: ParsedBookmarksData,
        result: ImportResult,
    ) -> Dict[str, int]:
        """Import folders from parsed data.

        Args:
            db_profile: The database browser profile
            parsed_data: Parsed bookmarks data
            result: ImportResult to update with statistics

        Returns:
            Mapping from browser folder ID to database folder ID
        """
        folder_id_map: Dict[str, int] = {}

        # Sort folders by path depth so parents are created before children
        sorted_folders = sorted(
            parsed_data.folders, key=lambda f: f.path.count("/")
        )

        for parsed_folder in sorted_folders:
            # Check if folder already exists
            existing = Folder.find_by_browser_id(
                self.db, db_profile.id, parsed_folder.browser_id
            )

            # Determine parent_id from our mapping
            parent_id = None
            if parsed_folder.parent_folder_id:
                parent_id = folder_id_map.get(parsed_folder.parent_folder_id)

            if existing:
                # Update existing folder
                existing.name = parsed_folder.name
                existing.parent_id = parent_id
                existing.browser_folder_path = parsed_folder.path
                existing.position = parsed_folder.position
                existing.save(self.db)
                folder_id_map[parsed_folder.browser_id] = existing.id
                result.folders_updated += 1
            else:
                # Create new folder
                folder = Folder(
                    name=parsed_folder.name,
                    parent_id=parent_id,
                    browser_profile_id=db_profile.id,
                    browser_folder_id=parsed_folder.browser_id,
                    browser_folder_path=parsed_folder.path,
                    position=parsed_folder.position,
                )
                folder.save(self.db)
                folder_id_map[parsed_folder.browser_id] = folder.id
                result.folders_added += 1

        return folder_id_map

    def _import_bookmarks(
        self,
        db_profile: BrowserProfile,
        parsed_data: ParsedBookmarksData,
        folder_id_map: Dict[str, int],
        result: ImportResult,
    ):
        """Import bookmarks from parsed data.

        Args:
            db_profile: The database browser profile
            parsed_data: Parsed bookmarks data
            folder_id_map: Mapping from browser folder ID to database folder ID
            result: ImportResult to update with statistics
        """
        for parsed_bookmark in parsed_data.bookmarks:
            # Check if bookmark already exists
            existing = Bookmark.find_by_browser_id(
                self.db, db_profile.id, parsed_bookmark.browser_id
            )

            # Determine folder_id from our mapping
            folder_id = None
            if parsed_bookmark.parent_folder_id:
                folder_id = folder_id_map.get(parsed_bookmark.parent_folder_id)

            if existing:
                # Update existing bookmark
                existing.url = parsed_bookmark.url
                existing.title = parsed_bookmark.title
                existing.folder_id = folder_id
                existing.browser_added_at = parsed_bookmark.date_added
                existing.position = parsed_bookmark.position
                existing.save(self.db)
                result.bookmarks_updated += 1
            else:
                # Create new bookmark
                bookmark = Bookmark(
                    url=parsed_bookmark.url,
                    title=parsed_bookmark.title,
                    folder_id=folder_id,
                    browser_profile_id=db_profile.id,
                    browser_bookmark_id=parsed_bookmark.browser_id,
                    browser_added_at=parsed_bookmark.date_added,
                    position=parsed_bookmark.position,
                )
                bookmark.save(self.db)
                result.bookmarks_added += 1

    def import_all_profiles(
        self, replace_existing: bool = False
    ) -> List[ImportResult]:
        """Import bookmarks from all detected browser profiles.

        Args:
            replace_existing: If True, replace existing bookmarks for each profile

        Returns:
            List of ImportResult for each profile
        """
        results = []
        profiles = self.detect_profiles()

        for profile in profiles:
            if profile.has_bookmarks_file:
                result = self.import_profile(profile, replace_existing)
                results.append(result)

        return results

    def get_import_summary(self) -> Dict:
        """Get a summary of what would be imported.

        Returns:
            Dictionary with import summary information
        """
        profiles = self.detect_profiles()

        summary = {
            "total_profiles": len(profiles),
            "profiles_with_bookmarks": sum(
                1 for p in profiles if p.has_bookmarks_file
            ),
            "total_bookmarks": sum(p.bookmark_count for p in profiles),
            "browsers": {},
        }

        for profile in profiles:
            if profile.browser_name not in summary["browsers"]:
                summary["browsers"][profile.browser_name] = {
                    "profiles": [],
                    "total_bookmarks": 0,
                }

            summary["browsers"][profile.browser_name]["profiles"].append({
                "profile_id": profile.profile_id,
                "profile_name": profile.profile_name or profile.profile_id,
                "bookmark_count": profile.bookmark_count,
                "has_bookmarks": profile.has_bookmarks_file,
            })
            summary["browsers"][profile.browser_name]["total_bookmarks"] += (
                profile.bookmark_count
            )

        return summary
