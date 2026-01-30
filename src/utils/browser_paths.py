"""Utility functions to detect browser installation paths."""

import os
import sys
from pathlib import Path
from typing import Dict, Optional


def get_browser_data_paths() -> Dict[str, Optional[Path]]:
    """Get the User Data paths for supported browsers.

    Returns:
        Dictionary mapping browser names to their User Data paths.
        Path is None if the browser is not found.
    """
    paths = {}

    if sys.platform == "win32":
        # Windows paths
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            local_app_data = Path(local_app_data)

            # Chrome
            chrome_path = local_app_data / "Google" / "Chrome" / "User Data"
            paths["Chrome"] = chrome_path if chrome_path.exists() else None

            # Edge
            edge_path = local_app_data / "Microsoft" / "Edge" / "User Data"
            paths["Edge"] = edge_path if edge_path.exists() else None

            # Brave
            brave_path = local_app_data / "BraveSoftware" / "Brave-Browser" / "User Data"
            paths["Brave"] = brave_path if brave_path.exists() else None

            # Vivaldi
            vivaldi_path = local_app_data / "Vivaldi" / "User Data"
            paths["Vivaldi"] = vivaldi_path if vivaldi_path.exists() else None

            # Opera
            roaming_app_data = os.environ.get("APPDATA", "")
            if roaming_app_data:
                opera_path = Path(roaming_app_data) / "Opera Software" / "Opera Stable"
                paths["Opera"] = opera_path if opera_path.exists() else None

    elif sys.platform == "darwin":
        # macOS paths
        home = Path.home()
        app_support = home / "Library" / "Application Support"

        # Chrome
        chrome_path = app_support / "Google" / "Chrome"
        paths["Chrome"] = chrome_path if chrome_path.exists() else None

        # Edge
        edge_path = app_support / "Microsoft Edge"
        paths["Edge"] = edge_path if edge_path.exists() else None

        # Brave
        brave_path = app_support / "BraveSoftware" / "Brave-Browser"
        paths["Brave"] = brave_path if brave_path.exists() else None

        # Vivaldi
        vivaldi_path = app_support / "Vivaldi"
        paths["Vivaldi"] = vivaldi_path if vivaldi_path.exists() else None

    else:
        # Linux paths
        home = Path.home()
        config = home / ".config"

        # Chrome
        chrome_path = config / "google-chrome"
        paths["Chrome"] = chrome_path if chrome_path.exists() else None

        # Edge
        edge_path = config / "microsoft-edge"
        paths["Edge"] = edge_path if edge_path.exists() else None

        # Brave
        brave_path = config / "BraveSoftware" / "Brave-Browser"
        paths["Brave"] = brave_path if brave_path.exists() else None

        # Vivaldi
        vivaldi_path = config / "vivaldi"
        paths["Vivaldi"] = vivaldi_path if vivaldi_path.exists() else None

    return paths


def get_installed_browsers() -> Dict[str, Path]:
    """Get only the browsers that are installed.

    Returns:
        Dictionary mapping browser names to their User Data paths.
        Only includes browsers that were found.
    """
    all_paths = get_browser_data_paths()
    return {name: path for name, path in all_paths.items() if path is not None}


def is_chromium_based(browser_name: str) -> bool:
    """Check if a browser is Chromium-based (uses same bookmark format).

    Args:
        browser_name: Name of the browser to check.

    Returns:
        True if the browser uses Chromium bookmark format.
    """
    chromium_browsers = {"Chrome", "Edge", "Brave", "Vivaldi", "Opera", "Chromium"}
    return browser_name in chromium_browsers
