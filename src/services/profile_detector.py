"""Service to detect browser profiles."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

from ..utils.browser_paths import get_installed_browsers, is_chromium_based


@dataclass
class DetectedProfile:
    """Represents a detected browser profile."""

    browser_name: str
    profile_id: str  # Directory name (e.g., "Default", "Profile 1")
    profile_name: Optional[str]  # User-friendly name from preferences
    profile_path: Path
    bookmark_count: int = 0
    has_bookmarks_file: bool = False


class ProfileDetector:
    """Detects browser profiles for Chromium-based browsers."""

    def __init__(self):
        self.installed_browsers = get_installed_browsers()

    def detect_all_profiles(self) -> List[DetectedProfile]:
        """Detect all profiles from all installed browsers.

        Returns:
            List of detected profiles with their metadata.
        """
        profiles = []

        for browser_name, user_data_path in self.installed_browsers.items():
            if is_chromium_based(browser_name):
                browser_profiles = self._detect_chromium_profiles(
                    browser_name, user_data_path
                )
                profiles.extend(browser_profiles)

        return profiles

    def detect_profiles_for_browser(self, browser_name: str) -> List[DetectedProfile]:
        """Detect all profiles for a specific browser.

        Args:
            browser_name: Name of the browser (e.g., "Chrome", "Edge")

        Returns:
            List of detected profiles for the specified browser.
        """
        if browser_name not in self.installed_browsers:
            return []

        user_data_path = self.installed_browsers[browser_name]
        if is_chromium_based(browser_name):
            return self._detect_chromium_profiles(browser_name, user_data_path)

        return []

    def _detect_chromium_profiles(
        self, browser_name: str, user_data_path: Path
    ) -> List[DetectedProfile]:
        """Detect profiles for a Chromium-based browser.

        Args:
            browser_name: Name of the browser
            user_data_path: Path to the User Data directory

        Returns:
            List of detected profiles
        """
        profiles = []

        if not user_data_path.exists():
            return profiles

        # Check for Default profile
        default_profile = self._check_profile_directory(
            browser_name, user_data_path / "Default", "Default"
        )
        if default_profile:
            profiles.append(default_profile)

        # Check for numbered profiles (Profile 1, Profile 2, etc.)
        for item in user_data_path.iterdir():
            if item.is_dir() and item.name.startswith("Profile "):
                profile = self._check_profile_directory(
                    browser_name, item, item.name
                )
                if profile:
                    profiles.append(profile)

        return profiles

    def _check_profile_directory(
        self, browser_name: str, profile_path: Path, profile_id: str
    ) -> Optional[DetectedProfile]:
        """Check if a directory is a valid browser profile.

        Args:
            browser_name: Name of the browser
            profile_path: Path to the profile directory
            profile_id: Profile identifier (directory name)

        Returns:
            DetectedProfile if valid, None otherwise
        """
        if not profile_path.exists():
            return None

        bookmarks_file = profile_path / "Bookmarks"
        has_bookmarks = bookmarks_file.exists()

        # Try to get the user-friendly profile name from Preferences
        profile_name = self._get_profile_name(profile_path)

        # Count bookmarks if file exists
        bookmark_count = 0
        if has_bookmarks:
            bookmark_count = self._count_bookmarks(bookmarks_file)

        return DetectedProfile(
            browser_name=browser_name,
            profile_id=profile_id,
            profile_name=profile_name,
            profile_path=profile_path,
            bookmark_count=bookmark_count,
            has_bookmarks_file=has_bookmarks,
        )

    def _get_profile_name(self, profile_path: Path) -> Optional[str]:
        """Get the user-friendly profile name from Preferences file.

        Prioritizes account info (email/full_name) over generic profile names
        like "Person 1" or "Profile 1".

        Args:
            profile_path: Path to the profile directory

        Returns:
            User-friendly profile name or None
        """
        preferences_file = profile_path / "Preferences"

        if not preferences_file.exists():
            return None

        try:
            with open(preferences_file, "r", encoding="utf-8") as f:
                prefs = json.load(f)

            # First, try to get account info (more meaningful than generic names)
            account_info = prefs.get("account_info", [])
            if account_info and len(account_info) > 0:
                account = account_info[0]
                # Prefer email as it's unique and identifiable
                email = account.get("email")
                if email:
                    return email
                # Fall back to full_name
                full_name = account.get("full_name")
                if full_name:
                    return full_name

            # Fall back to profile.name, but skip generic names
            profile_info = prefs.get("profile", {})
            name = profile_info.get("name")

            # Check if name is generic (Person 1, Profile 1, etc.)
            if name:
                # Skip generic names - we'll use profile_id instead
                generic_patterns = ["Person ", "Profile ", "User "]
                is_generic = any(name.startswith(p) for p in generic_patterns)
                if not is_generic:
                    return name

        except (json.JSONDecodeError, IOError, KeyError):
            pass

        return None

    def _count_bookmarks(self, bookmarks_file: Path) -> int:
        """Count the number of bookmarks in a bookmarks file.

        Args:
            bookmarks_file: Path to the Bookmarks file

        Returns:
            Number of bookmarks (approximate)
        """
        try:
            with open(bookmarks_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            roots = data.get("roots", {})

            for root_name, root_data in roots.items():
                if isinstance(root_data, dict):
                    count += self._count_bookmarks_recursive(root_data)

            return count

        except (json.JSONDecodeError, IOError):
            return 0

    def _count_bookmarks_recursive(self, node: dict) -> int:
        """Recursively count bookmarks in a node.

        Args:
            node: Bookmark node dictionary

        Returns:
            Number of bookmarks in this node and children
        """
        count = 0

        if node.get("type") == "url":
            count = 1
        elif node.get("type") == "folder":
            children = node.get("children", [])
            for child in children:
                count += self._count_bookmarks_recursive(child)

        return count

    def get_summary(self) -> Dict[str, any]:
        """Get a summary of detected browsers and profiles.

        Returns:
            Dictionary with summary information
        """
        profiles = self.detect_all_profiles()

        summary = {
            "installed_browsers": list(self.installed_browsers.keys()),
            "total_profiles": len(profiles),
            "total_bookmarks": sum(p.bookmark_count for p in profiles),
            "profiles_by_browser": {},
        }

        for profile in profiles:
            if profile.browser_name not in summary["profiles_by_browser"]:
                summary["profiles_by_browser"][profile.browser_name] = []

            summary["profiles_by_browser"][profile.browser_name].append({
                "profile_id": profile.profile_id,
                "profile_name": profile.profile_name,
                "bookmark_count": profile.bookmark_count,
                "has_bookmarks_file": profile.has_bookmarks_file,
            })

        return summary
