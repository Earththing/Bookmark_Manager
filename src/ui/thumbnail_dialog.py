"""Dialog for batch thumbnail generation."""

from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QCheckBox, QSpinBox, QTextEdit,
    QMessageBox, QRadioButton, QButtonGroup
)

from ..models.database import get_database
from ..models.bookmark import Bookmark
from ..services.thumbnail_service import get_thumbnail_service, check_playwright_available


class ThumbnailDialog(QDialog):
    """Dialog for generating thumbnails for bookmarks."""

    def __init__(self, selected_urls: Optional[List[str]] = None, parent=None):
        """Initialize the dialog.

        Args:
            selected_urls: If provided, only generate for these URLs.
                          If None, show options to generate for all.
            parent: Parent widget
        """
        super().__init__(parent)
        self.db = get_database()
        self.thumbnail_service = get_thumbnail_service()
        self.selected_urls = selected_urls

        self.setWindowTitle("Generate Thumbnails")
        self.setMinimumSize(500, 400)

        self.setup_ui()
        self.check_playwright()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Playwright status
        self.playwright_status = QLabel()
        self.playwright_status.setWordWrap(True)
        layout.addWidget(self.playwright_status)

        # Scope selection
        scope_group = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_group)

        self.scope_button_group = QButtonGroup(self)

        if self.selected_urls:
            self.scope_selected = QRadioButton(f"Selected bookmarks only ({len(self.selected_urls)} URLs)")
            self.scope_selected.setChecked(True)
            self.scope_button_group.addButton(self.scope_selected, 0)
            scope_layout.addWidget(self.scope_selected)

        self.scope_all = QRadioButton("All bookmarks")
        if not self.selected_urls:
            self.scope_all.setChecked(True)
        self.scope_button_group.addButton(self.scope_all, 1)
        scope_layout.addWidget(self.scope_all)

        self.scope_missing = QRadioButton("Bookmarks without thumbnails only")
        self.scope_button_group.addButton(self.scope_missing, 2)
        scope_layout.addWidget(self.scope_missing)

        layout.addWidget(scope_group)

        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self.skip_cached_check = QCheckBox("Skip URLs with existing thumbnails")
        self.skip_cached_check.setChecked(True)
        self.skip_cached_check.setToolTip("If checked, URLs that already have cached thumbnails will be skipped")
        options_layout.addWidget(self.skip_cached_check)

        # Concurrent workers (limited due to Playwright)
        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("Concurrent workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setMinimum(1)
        self.workers_spin.setMaximum(2)  # Limited for Playwright stability
        self.workers_spin.setValue(2)
        self.workers_spin.setToolTip("Number of concurrent screenshot captures (limited to 2 for stability)")
        workers_layout.addWidget(self.workers_spin)
        workers_layout.addStretch()
        options_layout.addLayout(workers_layout)

        layout.addWidget(options_group)

        # Cache info
        cache_group = QGroupBox("Cache Information")
        cache_layout = QVBoxLayout(cache_group)

        self.cache_info_label = QLabel()
        self.update_cache_info()
        cache_layout.addWidget(self.cache_info_label)

        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.clicked.connect(self.clear_cache)
        cache_layout.addWidget(clear_cache_btn)

        layout.addWidget(cache_group)

        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Ready to generate thumbnails")
        progress_layout.addWidget(self.progress_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setVisible(False)
        progress_layout.addWidget(self.log_text)

        layout.addWidget(progress_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Generation")
        self.start_btn.clicked.connect(self.start_generation)
        button_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_generation)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.cancel_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        # Connect service signals
        self.thumbnail_service.batch_progress.connect(self.on_progress)
        self.thumbnail_service.batch_thumbnail_generated.connect(self.on_thumbnail_generated)
        self.thumbnail_service.batch_finished.connect(self.on_finished)

    def check_playwright(self):
        """Check if Playwright is available."""
        if check_playwright_available():
            self.playwright_status.setText(
                "✅ <b>Playwright is installed and ready.</b> "
                "Thumbnails will be generated using a headless browser."
            )
            self.playwright_status.setStyleSheet("color: green;")
            self.start_btn.setEnabled(True)
        else:
            self.playwright_status.setText(
                "⚠️ <b>Playwright is not installed or not configured.</b>\n\n"
                "To enable thumbnail generation, install Playwright:\n"
                "<code>pip install playwright</code>\n"
                "<code>playwright install chromium</code>\n\n"
                "Without Playwright, only placeholder images will be generated."
            )
            self.playwright_status.setStyleSheet("color: #cc7700; background-color: #fff3cd; padding: 10px; border-radius: 4px;")
            # Still allow starting - will generate placeholders
            self.start_btn.setEnabled(True)

    def update_cache_info(self):
        """Update cache information display."""
        count, size = self.thumbnail_service.get_cache_size()
        size_mb = size / (1024 * 1024)
        self.cache_info_label.setText(
            f"Cached thumbnails: {count}\n"
            f"Cache size: {size_mb:.1f} MB\n"
            f"Cache location: {self.thumbnail_service.cache_dir}"
        )

    def clear_cache(self):
        """Clear the thumbnail cache."""
        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to delete all cached thumbnails?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.thumbnail_service.clear_cache()
            self.update_cache_info()
            QMessageBox.information(self, "Cache Cleared", "Thumbnail cache has been cleared.")

    def get_urls_to_process(self) -> List[str]:
        """Get the list of URLs to process based on selected scope."""
        scope = self.scope_button_group.checkedId()

        if scope == 0 and self.selected_urls:
            # Selected URLs only
            return self.selected_urls
        elif scope == 1:
            # All bookmarks
            bookmarks = Bookmark.get_all(self.db)
            return [b.url for b in bookmarks]
        elif scope == 2:
            # Missing thumbnails only
            bookmarks = Bookmark.get_all(self.db)
            return [b.url for b in bookmarks
                    if not self.thumbnail_service.has_cached_thumbnail(b.url)]
        else:
            return []

    def start_generation(self):
        """Start the thumbnail generation process."""
        urls = self.get_urls_to_process()

        if not urls:
            QMessageBox.information(
                self,
                "No URLs",
                "No URLs to process. All bookmarks may already have thumbnails."
            )
            return

        # Update UI for running state
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(urls))
        self.progress_bar.setValue(0)
        self.log_text.setVisible(True)
        self.log_text.clear()

        self.progress_label.setText(f"Processing {len(urls)} URLs...")

        # Start batch generation
        skip_cached = self.skip_cached_check.isChecked()
        workers = self.workers_spin.value()

        success = self.thumbnail_service.generate_batch(
            urls=urls,
            max_workers=workers,
            skip_cached=skip_cached
        )

        if not success:
            QMessageBox.warning(
                self,
                "Already Running",
                "A batch thumbnail generation is already in progress."
            )
            self.reset_ui()

    def cancel_generation(self):
        """Cancel the running generation."""
        self.thumbnail_service.cancel_batch()
        self.progress_label.setText("Cancelling...")
        self.cancel_btn.setEnabled(False)

    def on_progress(self, current: int, total: int, url: str):
        """Handle progress update."""
        self.progress_bar.setValue(current)
        # Truncate URL for display
        display_url = url[:60] + "..." if len(url) > 60 else url
        self.progress_label.setText(f"Processing {current}/{total}: {display_url}")

    def on_thumbnail_generated(self, url: str, success: bool, error: str):
        """Handle individual thumbnail result."""
        display_url = url[:50] + "..." if len(url) > 50 else url

        if success:
            if error == "cached":
                self.log_text.append(f"⏭️ Skipped (cached): {display_url}")
            else:
                self.log_text.append(f"✅ Generated: {display_url}")
        else:
            self.log_text.append(f"❌ Failed: {display_url} - {error[:30]}")

        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_finished(self, success_count: int, error_count: int):
        """Handle batch completion."""
        self.reset_ui()
        self.update_cache_info()

        total = success_count + error_count
        self.progress_label.setText(
            f"Completed: {success_count} successful, {error_count} failed out of {total} URLs"
        )

        if error_count == 0:
            QMessageBox.information(
                self,
                "Generation Complete",
                f"Successfully generated {success_count} thumbnails."
            )
        else:
            QMessageBox.warning(
                self,
                "Generation Complete",
                f"Generated {success_count} thumbnails.\n"
                f"{error_count} URLs failed (see log for details)."
            )

    def reset_ui(self):
        """Reset UI to ready state."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.thumbnail_service.is_batch_running():
            reply = QMessageBox.question(
                self,
                "Generation in Progress",
                "Thumbnail generation is still running. Cancel it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.thumbnail_service.cancel_batch()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
