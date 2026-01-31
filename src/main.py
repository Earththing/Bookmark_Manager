"""Main entry point for the Bookmark Manager application."""

import sys
from pathlib import Path

from .models.database import get_database
from .models.bookmark import Bookmark
from .models.folder import Folder
from .models.browser_profile import BrowserProfile
from .services.import_service import ImportService, ImportProgress


def create_progress_bar(current: int, total: int, width: int = 40) -> str:
    """Create an ASCII progress bar.

    Args:
        current: Current progress value
        total: Total value
        width: Width of the bar in characters

    Returns:
        Progress bar string like [####----] 50%
    """
    if total == 0:
        return f"[{'-' * width}] 0%"

    percentage = current / total
    filled = int(width * percentage)
    empty = width - filled

    return f"[{'#' * filled}{'-' * empty}] {int(percentage * 100)}%"


def truncate_string(s: str, max_len: int) -> str:
    """Truncate a string to max length, adding ... if needed."""
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def print_progress(progress: ImportProgress):
    """Print progress update on a single line."""
    bar = create_progress_bar(progress.current_item, progress.total_items, 30)
    title = truncate_string(progress.current_title, 40)

    # Use carriage return to overwrite the line
    status = f"\r{bar} {progress.phase}: {title:<40}"

    # Print without newline, flush to ensure immediate display
    sys.stdout.write(status)
    sys.stdout.flush()


def main():
    """Main function to demonstrate bookmark import functionality."""
    print("=" * 60)
    print("Bookmark Manager - Browser Import Tool")
    print("=" * 60)

    # Initialize database
    db = get_database()
    print(f"\nDatabase location: {db.db_path}")

    # Show current database stats
    current_bookmark_count = Bookmark.count(db)
    if current_bookmark_count > 0:
        print(f"Current bookmarks in database: {current_bookmark_count}")

    # Create import service
    import_service = ImportService(db)

    # Show what profiles are available
    print("\n--- Detected Browser Profiles ---")
    summary = import_service.get_import_summary()

    print(f"Total profiles found: {summary['total_profiles']}")
    print(f"Profiles with bookmarks: {summary['profiles_with_bookmarks']}")
    print(f"Total bookmarks across all profiles: {summary['total_bookmarks']}")

    for browser_name, browser_data in summary["browsers"].items():
        print(f"\n{browser_name}:")
        for profile in browser_data["profiles"]:
            status = "+" if profile["has_bookmarks"] else "-"
            print(
                f"  [{status}] {profile['profile_name']}: "
                f"{profile['bookmark_count']} bookmarks"
            )

    if summary["total_bookmarks"] == 0:
        print("\nNo bookmarks found to import.")
        return

    # Ask user to confirm import
    print("\n" + "-" * 60)
    print("Note: Only NEW bookmarks will be imported. Existing ones will be skipped.")
    response = input("Do you want to import these bookmarks? (y/n): ").strip().lower()

    if response != "y":
        print("Import cancelled.")
        return

    # Perform import with progress callback
    print("\nImporting bookmarks...\n")
    results = import_service.import_all_profiles(progress_callback=print_progress)

    # Clear the progress line and move to next line
    print("\n")

    # Show results
    print("--- Import Results ---")
    total_added = 0
    total_skipped = 0

    for result in results:
        print(
            f"\n{result.profile.browser_name} - "
            f"{result.profile.profile_display_name or result.profile.browser_profile_name}:"
        )
        print(
            f"  Folders: {result.folders_added} added, "
            f"{result.folders_skipped} already existed"
        )
        print(
            f"  Bookmarks: {result.bookmarks_added} added, "
            f"{result.bookmarks_skipped} already existed"
        )

        if result.errors:
            print(f"  Errors: {len(result.errors)}")
            for error in result.errors:
                print(f"    - {error}")

        total_added += result.bookmarks_added
        total_skipped += result.bookmarks_skipped

    # Show summary
    print("\n--- Summary ---")
    print(f"Bookmarks added: {total_added}")
    print(f"Bookmarks skipped (already existed): {total_skipped}")
    print(f"Total bookmarks in database: {Bookmark.count(db)}")

    print("\n" + "=" * 60)
    print("Import complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
