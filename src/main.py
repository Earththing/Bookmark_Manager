"""Main entry point for the Bookmark Manager application."""

import json
from pathlib import Path

from .models.database import get_database, reset_database
from .models.bookmark import Bookmark
from .models.folder import Folder
from .models.browser_profile import BrowserProfile
from .services.import_service import ImportService


def main():
    """Main function to demonstrate bookmark import functionality."""
    print("=" * 60)
    print("Bookmark Manager - Browser Import Tool")
    print("=" * 60)

    # Initialize database
    db = get_database()
    print(f"\nDatabase location: {db.db_path}")

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
            status = "✓" if profile["has_bookmarks"] else "✗"
            print(
                f"  [{status}] {profile['profile_name']}: "
                f"{profile['bookmark_count']} bookmarks"
            )

    if summary["total_bookmarks"] == 0:
        print("\nNo bookmarks found to import.")
        return

    # Ask user to confirm import
    print("\n" + "-" * 60)
    response = input("Do you want to import these bookmarks? (y/n): ").strip().lower()

    if response != "y":
        print("Import cancelled.")
        return

    # Perform import
    print("\nImporting bookmarks...")
    results = import_service.import_all_profiles(replace_existing=True)

    # Show results
    print("\n--- Import Results ---")
    total_bookmarks = 0
    total_folders = 0

    for result in results:
        print(
            f"\n{result.profile.browser_name} - "
            f"{result.profile.profile_name or result.profile.profile_id}:"
        )
        print(f"  Folders: {result.folders_added} added, {result.folders_updated} updated")
        print(
            f"  Bookmarks: {result.bookmarks_added} added, "
            f"{result.bookmarks_updated} updated"
        )

        if result.errors:
            print(f"  Errors: {len(result.errors)}")
            for error in result.errors:
                print(f"    - {error}")

        total_bookmarks += result.bookmarks_added + result.bookmarks_updated
        total_folders += result.folders_added + result.folders_updated

    # Show database stats
    print("\n--- Database Statistics ---")
    print(f"Total bookmarks in database: {Bookmark.count(db)}")
    print(f"Total profiles in database: {len(BrowserProfile.get_all(db))}")

    # Show some sample bookmarks
    print("\n--- Sample Bookmarks (first 10) ---")
    all_bookmarks = Bookmark.get_all(db)[:10]
    for bm in all_bookmarks:
        title = bm.title[:50] + "..." if bm.title and len(bm.title) > 50 else bm.title
        print(f"  - {title}")
        print(f"    URL: {bm.url[:60]}...")

    print("\n" + "=" * 60)
    print("Import complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
