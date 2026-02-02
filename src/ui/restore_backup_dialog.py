"""Dialog for restoring browser bookmarks from a backup."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QListWidget, QListWidgetItem, QMessageBox,
    QTextEdit, QSplitter, QCheckBox
)

from ..services.browser_process import BrowserProcessService


class RestoreBackupDialog(QDialog):
    """Dialog for restoring browser bookmarks from backups."""

    def __init__(self, backup_dir: Path, parent=None):
        super().__init__(parent)
        self.backup_dir = backup_dir
        self.selected_backup: Optional[Path] = None
        self.backup_info: Dict = {}

        self.setWindowTitle("Restore Bookmarks from Backup")
        self.setMinimumSize(700, 500)
        self.setup_ui()
        self.load_backups()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Info label
        info_label = QLabel(
            "Select a backup to restore. This will replace the browser's current bookmarks "
            "with the backup. The browser must be closed before restoring."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left - backup list
        left_widget = QGroupBox("Available Backups")
        left_layout = QVBoxLayout(left_widget)

        self.backup_list = QListWidget()
        self.backup_list.currentItemChanged.connect(self.on_backup_selected)
        left_layout.addWidget(self.backup_list)

        splitter.addWidget(left_widget)

        # Right - backup details
        right_widget = QGroupBox("Backup Details")
        right_layout = QVBoxLayout(right_widget)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        right_layout.addWidget(self.details_text)

        splitter.addWidget(right_widget)

        splitter.setSizes([350, 350])
        layout.addWidget(splitter)

        # Buttons
        button_layout = QHBoxLayout()

        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.load_backups)
        button_layout.addWidget(refresh_btn)

        open_folder_btn = QPushButton("Open Backup Folder")
        open_folder_btn.clicked.connect(self.open_backup_folder)
        button_layout.addWidget(open_folder_btn)

        button_layout.addStretch()

        self.restore_btn = QPushButton("Restore Selected Backup")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self.restore_backup)
        button_layout.addWidget(self.restore_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def load_backups(self):
        """Load list of available backups."""
        self.backup_list.clear()
        self.backup_info.clear()

        if not self.backup_dir.exists():
            self.details_text.setPlainText("No backups found.\n\nBackups are created automatically when you delete bookmarks from browsers.")
            return

        # Find all backup files
        backups = list(self.backup_dir.glob("*_Bookmarks_*.json"))
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not backups:
            self.details_text.setPlainText("No backups found.\n\nBackups are created automatically when you delete bookmarks from browsers.")
            return

        for backup_path in backups:
            # Parse filename: Browser_Profile_Bookmarks_YYYYMMDD_HHMMSS.json
            filename = backup_path.stem  # Without .json
            parts = filename.split("_Bookmarks_")

            if len(parts) == 2:
                browser_profile = parts[0]
                timestamp_str = parts[1]

                # Parse timestamp
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    display_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    display_time = timestamp_str

                # Get file size
                size_kb = backup_path.stat().st_size / 1024

                # Create list item
                item = QListWidgetItem(f"{browser_profile} - {display_time}")
                item.setData(Qt.ItemDataRole.UserRole, backup_path)
                self.backup_list.addItem(item)

                # Store info
                self.backup_info[str(backup_path)] = {
                    'browser_profile': browser_profile,
                    'timestamp': display_time,
                    'size_kb': size_kb,
                    'path': backup_path
                }

    def on_backup_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Handle backup selection."""
        if current is None:
            self.selected_backup = None
            self.restore_btn.setEnabled(False)
            self.details_text.clear()
            return

        backup_path = current.data(Qt.ItemDataRole.UserRole)
        self.selected_backup = backup_path
        self.restore_btn.setEnabled(True)

        # Show details
        info = self.backup_info.get(str(backup_path), {})

        details = f"<h3>{info.get('browser_profile', 'Unknown')}</h3>"
        details += f"<p><b>Backup Date:</b> {info.get('timestamp', 'Unknown')}</p>"
        details += f"<p><b>File Size:</b> {info.get('size_kb', 0):.1f} KB</p>"
        details += f"<p><b>File Path:</b><br><small>{backup_path}</small></p>"

        # Try to read bookmark count from file
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            bookmark_count = self._count_bookmarks(data)
            details += f"<p><b>Bookmarks in backup:</b> {bookmark_count}</p>"
        except Exception as e:
            details += f"<p style='color: red;'>Could not read backup: {e}</p>"

        # Determine target browser/profile
        browser_profile = info.get('browser_profile', '')
        parts = browser_profile.split("_", 1)
        if len(parts) == 2:
            browser_name = parts[0]
            profile_name = parts[1]
            details += f"<hr><p><b>Will restore to:</b><br>{browser_name} / {profile_name}</p>"

            # Check if browser is running
            if BrowserProcessService.is_browser_running(browser_name):
                details += f"<p style='color: #856404; background-color: #fff3cd; padding: 8px;'>"
                details += f"\u26a0\ufe0f {browser_name} is currently running and must be closed before restoring."
                details += "</p>"

        self.details_text.setHtml(details)

    def _count_bookmarks(self, data: dict) -> int:
        """Count bookmarks in a bookmark data structure."""
        count = 0

        def count_in_node(node):
            nonlocal count
            if node.get('type') == 'url':
                count += 1
            if 'children' in node:
                for child in node['children']:
                    count_in_node(child)

        if 'roots' in data:
            for root in data['roots'].values():
                if isinstance(root, dict):
                    count_in_node(root)

        return count

    def open_backup_folder(self):
        """Open the backup folder in file explorer."""
        import os
        import subprocess

        if self.backup_dir.exists():
            # Windows
            subprocess.run(['explorer', str(self.backup_dir)])
        else:
            QMessageBox.information(
                self,
                "No Backups",
                f"Backup folder does not exist yet:\n\n{self.backup_dir}"
            )

    def restore_backup(self):
        """Restore the selected backup."""
        if not self.selected_backup or not self.selected_backup.exists():
            QMessageBox.warning(self, "Error", "Please select a valid backup.")
            return

        # Parse browser and profile from filename
        info = self.backup_info.get(str(self.selected_backup), {})
        browser_profile = info.get('browser_profile', '')
        parts = browser_profile.split("_", 1)

        if len(parts) != 2:
            QMessageBox.warning(
                self,
                "Error",
                "Could not determine browser/profile from backup filename."
            )
            return

        browser_name = parts[0]
        profile_name = parts[1]

        # Check if browser is running
        if BrowserProcessService.is_browser_running(browser_name):
            reply = QMessageBox.question(
                self,
                "Browser Running",
                f"{browser_name} is currently running.\n\n"
                "It must be closed before restoring bookmarks.\n\n"
                "Would you like to close it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                success, message = BrowserProcessService.close_browser(browser_name)
                if not success:
                    QMessageBox.warning(self, "Could Not Close Browser", message)
                    return
            else:
                return

        # Find the target bookmarks file
        target_path = self._find_profile_path(browser_name, profile_name)

        if not target_path:
            QMessageBox.warning(
                self,
                "Profile Not Found",
                f"Could not find the profile path for {browser_name}/{profile_name}.\n\n"
                "The profile may have been deleted or moved."
            )
            return

        bookmarks_file = target_path / "Bookmarks"

        # Confirm restore
        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            f"This will replace all bookmarks in:\n\n"
            f"  {browser_name} / {profile_name}\n\n"
            f"with the backup from {info.get('timestamp', 'unknown date')}.\n\n"
            f"Current bookmarks will be OVERWRITTEN.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Create a backup of current state before restoring
        if bookmarks_file.exists():
            current_backup = self.backup_dir / f"{browser_name}_{profile_name}_BeforeRestore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copy2(bookmarks_file, current_backup)

        # Restore the backup
        try:
            shutil.copy2(self.selected_backup, bookmarks_file)
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Restore Failed",
                f"Failed to restore backup:\n\n{str(e)}"
            )

    def _find_profile_path(self, browser_name: str, profile_name: str) -> Optional[Path]:
        """Find the path to a browser profile."""
        import os

        local_app_data = os.environ.get('LOCALAPPDATA', '')

        if browser_name == "Chrome":
            base_path = Path(local_app_data) / "Google" / "Chrome" / "User Data"
        elif browser_name == "Edge":
            base_path = Path(local_app_data) / "Microsoft" / "Edge" / "User Data"
        else:
            return None

        # Try to find the profile
        # Profile name might be "Default", "Profile 1", etc.
        # Our backup uses underscores instead of spaces

        # Try exact match first
        profile_path = base_path / profile_name
        if profile_path.exists():
            return profile_path

        # Try with space instead of underscore
        profile_path = base_path / profile_name.replace("_", " ")
        if profile_path.exists():
            return profile_path

        # Search all profiles
        for item in base_path.iterdir():
            if item.is_dir():
                # Check if name matches (case-insensitive, with or without spaces)
                item_name_normalized = item.name.lower().replace(" ", "_")
                profile_name_normalized = profile_name.lower().replace(" ", "_")

                if item_name_normalized == profile_name_normalized:
                    return item

        return None
