"""Service to parse browser bookmark files."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class ParsedBookmark:
    """Represents a parsed bookmark from a browser file."""

    browser_id: str  # Original ID from browser
    url: str
    title: str
    date_added: Optional[datetime] = None
    parent_folder_id: Optional[str] = None
    position: int = 0


@dataclass
class ParsedFolder:
    """Represents a parsed folder from a browser file."""

    browser_id: str  # Original ID from browser
    name: str
    parent_folder_id: Optional[str] = None
    path: str = ""  # Full path like "Bookmarks Bar/Work/Projects"
    position: int = 0


@dataclass
class ParsedBookmarksData:
    """Container for all parsed data from a bookmark file."""

    bookmarks: List[ParsedBookmark] = field(default_factory=list)
    folders: List[ParsedFolder] = field(default_factory=list)
    checksum: Optional[str] = None
    version: Optional[int] = None


class BookmarkParser:
    """Parses Chromium-based browser bookmark files."""

    # Chrome/Edge use WebKit timestamps: microseconds since Jan 1, 1601
    WEBKIT_EPOCH = datetime(1601, 1, 1)

    def parse_file(self, bookmarks_path: Path) -> ParsedBookmarksData:
        """Parse a Chromium bookmarks file.

        Args:
            bookmarks_path: Path to the Bookmarks JSON file

        Returns:
            ParsedBookmarksData containing all bookmarks and folders
        """
        result = ParsedBookmarksData()

        if not bookmarks_path.exists():
            return result

        try:
            with open(bookmarks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading bookmark file {bookmarks_path}: {e}")
            return result

        result.checksum = data.get("checksum")
        result.version = data.get("version")

        roots = data.get("roots", {})

        # Process each root folder
        for root_name, root_data in roots.items():
            if isinstance(root_data, dict) and root_data.get("type") == "folder":
                self._parse_node(
                    node=root_data,
                    parent_folder_id=None,
                    current_path="",
                    result=result,
                    position=0,
                )

        return result

    def _parse_node(
        self,
        node: dict,
        parent_folder_id: Optional[str],
        current_path: str,
        result: ParsedBookmarksData,
        position: int,
    ):
        """Recursively parse a bookmark node.

        Args:
            node: The bookmark node dictionary
            parent_folder_id: ID of the parent folder
            current_path: Current path in the folder hierarchy
            result: ParsedBookmarksData to append results to
            position: Position of this node in its parent
        """
        node_type = node.get("type")
        node_id = node.get("id")
        name = node.get("name", "")

        if node_type == "folder":
            # Build the folder path
            if current_path:
                folder_path = f"{current_path}/{name}"
            else:
                folder_path = name

            folder = ParsedFolder(
                browser_id=node_id,
                name=name,
                parent_folder_id=parent_folder_id,
                path=folder_path,
                position=position,
            )
            result.folders.append(folder)

            # Parse children
            children = node.get("children", [])
            for i, child in enumerate(children):
                self._parse_node(
                    node=child,
                    parent_folder_id=node_id,
                    current_path=folder_path,
                    result=result,
                    position=i,
                )

        elif node_type == "url":
            url = node.get("url", "")
            date_added = self._parse_webkit_timestamp(node.get("date_added"))

            bookmark = ParsedBookmark(
                browser_id=node_id,
                url=url,
                title=name,
                date_added=date_added,
                parent_folder_id=parent_folder_id,
                position=position,
            )
            result.bookmarks.append(bookmark)

    def _parse_webkit_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """Convert a WebKit timestamp to a Python datetime.

        WebKit timestamps are microseconds since January 1, 1601.

        Args:
            timestamp_str: WebKit timestamp as a string

        Returns:
            Python datetime or None if parsing fails
        """
        if not timestamp_str:
            return None

        try:
            # WebKit timestamp is in microseconds
            microseconds = int(timestamp_str)

            # Convert to seconds and add to epoch
            from datetime import timedelta

            delta = timedelta(microseconds=microseconds)
            dt = self.WEBKIT_EPOCH + delta

            # Sanity check - should be after 1970 and before 2100
            if dt.year < 1970 or dt.year > 2100:
                return None

            return dt

        except (ValueError, OverflowError):
            return None

    def get_root_folders(self, bookmarks_path: Path) -> List[str]:
        """Get the names of root folders in a bookmarks file.

        Args:
            bookmarks_path: Path to the Bookmarks JSON file

        Returns:
            List of root folder names
        """
        try:
            with open(bookmarks_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            roots = data.get("roots", {})
            return [
                name
                for name, node in roots.items()
                if isinstance(node, dict) and node.get("type") == "folder"
            ]

        except (json.JSONDecodeError, IOError):
            return []
