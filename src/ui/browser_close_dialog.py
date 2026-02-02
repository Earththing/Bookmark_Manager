"""Dialog for closing browsers before modifying bookmarks."""

from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QMessageBox, QProgressBar
)

from ..services.browser_process import BrowserProcessService, BrowserProcess


class BrowserCloseDialog(QDialog):
    """Dialog for closing browsers before bookmark modification."""

    def __init__(self, running_browsers: List[BrowserProcess], parent=None):
        super().__init__(parent)
        # Only store the browsers that were explicitly passed (affected browsers)
        self.running_browsers = running_browsers
        self.browsers_to_close: List[str] = []
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_browsers_closed)

        # Build the title with browser names for clarity
        browser_names = [b.browser_name for b in running_browsers]
        self.setWindowTitle(f"Close Browsers: {', '.join(browser_names)}")
        self.setMinimumWidth(450)
        self.setup_ui()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Get the list of browser names for display
        browser_names = [b.browser_name for b in self.running_browsers]

        # Warning message
        warning_label = QLabel(
            "<h3>\u26a0\ufe0f Browsers Need to Close</h3>"
            f"<p>The following browser(s) must be closed before bookmarks can be deleted: <b>{', '.join(browser_names)}</b></p>"
            "<p><i>Browsers keep bookmarks in memory, so changes can only be saved when they're closed.</i></p>"
        )
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # Browser checkboxes
        browsers_group = QGroupBox("Running Browsers (uncheck to skip)")
        browsers_layout = QVBoxLayout(browsers_group)

        self.browser_checks = {}
        for browser in self.running_browsers:
            check = QCheckBox(f"{browser.browser_name}")
            check.setChecked(True)
            check.stateChanged.connect(self.update_buttons)
            self.browser_checks[browser.browser_name] = check
            browsers_layout.addWidget(check)

        layout.addWidget(browsers_group)

        # Status area
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        # Buttons - two rows for clarity
        button_layout1 = QHBoxLayout()

        self.close_for_me_btn = QPushButton("\u2713 Close Browsers for Me (Recommended)")
        self.close_for_me_btn.setStyleSheet(
            "background-color: #0d6efd; color: white; font-weight: bold; padding: 8px 16px;"
        )
        self.close_for_me_btn.clicked.connect(self.close_browsers_for_user)
        self.close_for_me_btn.setDefault(True)
        button_layout1.addWidget(self.close_for_me_btn)

        layout.addLayout(button_layout1)

        button_layout2 = QHBoxLayout()

        self.ill_close_btn = QPushButton("I'll Close Them Myself")
        self.ill_close_btn.setToolTip("Wait while you manually close the browsers")
        self.ill_close_btn.clicked.connect(self.wait_for_user_close)
        button_layout2.addWidget(self.ill_close_btn)

        self.skip_btn = QPushButton("Skip These Browsers")
        self.skip_btn.setToolTip("Don't delete bookmarks from these browsers")
        self.skip_btn.clicked.connect(self.skip_browsers)
        button_layout2.addWidget(self.skip_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout2.addWidget(self.cancel_btn)

        layout.addLayout(button_layout2)

    def update_buttons(self):
        """Update button states based on selections."""
        any_selected = any(check.isChecked() for check in self.browser_checks.values())
        self.close_for_me_btn.setEnabled(any_selected)
        self.ill_close_btn.setEnabled(any_selected)

    def get_selected_browsers(self) -> List[str]:
        """Get list of selected browser names."""
        return [
            name for name, check in self.browser_checks.items()
            if check.isChecked()
        ]

    def close_browsers_for_user(self):
        """Close the selected browsers automatically (only the affected ones)."""
        self.browsers_to_close = self.get_selected_browsers()

        # Double-check we're only closing browsers that were passed to us
        valid_browser_names = {b.browser_name for b in self.running_browsers}
        self.browsers_to_close = [b for b in self.browsers_to_close if b in valid_browser_names]

        if not self.browsers_to_close:
            self.accept()
            return

        self.set_ui_waiting(True)
        self.status_label.setText(f"Closing only: {', '.join(self.browsers_to_close)}...")

        # Try to close each browser
        failed = []
        for browser_name in self.browsers_to_close:
            success, message = BrowserProcessService.close_browser(browser_name, force=False)
            if not success:
                failed.append(browser_name)

        if failed:
            # Try force close
            reply = QMessageBox.question(
                self,
                "Browser Won't Close",
                f"The following browsers didn't close gracefully:\n\n"
                f"{', '.join(failed)}\n\n"
                "Do you want to force close them? (Unsaved work may be lost)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                for browser_name in failed:
                    BrowserProcessService.close_browser(browser_name, force=True)

        # Check if all are closed now
        self.check_browsers_closed()

    def wait_for_user_close(self):
        """Wait for user to close browsers manually."""
        self.browsers_to_close = self.get_selected_browsers()

        if not self.browsers_to_close:
            self.accept()
            return

        self.set_ui_waiting(True)
        self.status_label.setText(
            f"Please close {', '.join(self.browsers_to_close)}...\n"
            "This dialog will automatically continue when the browsers are closed."
        )

        # Start checking periodically
        self.check_timer.start(1000)  # Check every second

    def check_browsers_closed(self):
        """Check if the target browsers are closed."""
        still_running = []

        for browser_name in self.browsers_to_close:
            if BrowserProcessService.is_browser_running(browser_name):
                still_running.append(browser_name)

        if not still_running:
            # All closed!
            self.check_timer.stop()
            self.status_label.setText("All browsers closed!")
            self.accept()
        else:
            self.status_label.setText(
                f"Waiting for: {', '.join(still_running)}...\n"
                "This dialog will automatically continue when the browsers are closed."
            )

    def skip_browsers(self):
        """Skip the selected browsers (don't modify their bookmarks)."""
        selected = self.get_selected_browsers()

        if not selected:
            self.accept()
            return

        # Remove skipped browsers from parent's deletion list
        # This is handled by the parent dialog checking which browsers are still running
        # We just accept here - parent will re-check

        reply = QMessageBox.warning(
            self,
            "Skip Browsers",
            f"Bookmarks in the following browsers will NOT be deleted:\n\n"
            f"{', '.join(selected)}\n\n"
            "Continue with the remaining browsers?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Mark these as "don't need to close" by unchecking them
            for browser_name in selected:
                self.browser_checks[browser_name].setChecked(False)

            # If no browsers left to close, accept
            remaining = self.get_selected_browsers()
            if not remaining:
                self.accept()

    def set_ui_waiting(self, waiting: bool):
        """Set UI to waiting state."""
        self.progress_bar.setVisible(waiting)
        self.close_for_me_btn.setEnabled(not waiting)
        self.ill_close_btn.setEnabled(not waiting)
        self.skip_btn.setEnabled(not waiting)

        for check in self.browser_checks.values():
            check.setEnabled(not waiting)

    def reject(self):
        """Handle dialog rejection."""
        self.check_timer.stop()
        super().reject()

    def closeEvent(self, event):
        """Handle dialog close."""
        self.check_timer.stop()
        super().closeEvent(event)
