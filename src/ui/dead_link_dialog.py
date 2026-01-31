"""Dead Link Detection Dialog with progress tracking."""

import urllib.request
import urllib.error
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSpinBox, QCheckBox, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from ..models.database import Database, get_database
from ..models.bookmark import Bookmark


@dataclass
class DeadLinkResult:
    """Result of checking a single bookmark."""
    bookmark_id: int
    title: str
    url: str
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    is_dead: bool = False


@dataclass
class CheckProgress:
    """Progress information for dead link checking."""
    current: int = 0
    total: int = 0
    current_url: str = ""
    current_title: str = ""
    dead_count: int = 0
    checked_count: int = 0


def check_single_url(url: str, timeout: int, check_ssl: bool) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Check if a URL is accessible (standalone function for thread pool).

    Returns: (is_dead, status_code, error_message)
    """
    try:
        # Create SSL context
        if check_ssl:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        # Create request with a browser-like User-Agent
        request = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            },
            method='HEAD'  # Use HEAD request to be faster and more polite
        )

        # Try HEAD request first
        try:
            response = urllib.request.urlopen(
                request,
                timeout=timeout,
                context=ssl_context
            )
            return (False, response.getcode(), None)
        except urllib.error.HTTPError as e:
            # Some servers don't support HEAD, try GET
            if e.code == 405:  # Method Not Allowed
                request.method = 'GET'
                response = urllib.request.urlopen(
                    request,
                    timeout=timeout,
                    context=ssl_context
                )
                return (False, response.getcode(), None)
            # Consider 4xx and 5xx as potentially dead
            if e.code >= 400:
                return (True, e.code, f"HTTP {e.code}: {e.reason}")
            return (False, e.code, None)

    except urllib.error.URLError as e:
        return (True, None, f"URL Error: {str(e.reason)}")
    except ssl.SSLError as e:
        return (True, None, f"SSL Error: {str(e)}")
    except TimeoutError:
        return (True, None, "Timeout")
    except Exception as e:
        return (True, None, f"Error: {str(e)}")


class DeadLinkWorker(QThread):
    """Worker thread to check bookmarks for dead links using parallel requests."""

    progress_updated = pyqtSignal(CheckProgress)
    link_checked = pyqtSignal(DeadLinkResult)
    finished_checking = pyqtSignal(list)  # List of DeadLinkResult for dead links
    error_occurred = pyqtSignal(str)

    def __init__(self, db_path: str, timeout: int = 10, check_ssl: bool = True, max_workers: int = 10):
        super().__init__()
        self.db_path = db_path
        self.timeout = timeout
        self.check_ssl = check_ssl
        self.max_workers = max_workers
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the check."""
        self._cancelled = True

    def run(self):
        """Run the dead link check with parallel URL checking."""
        try:
            # Create thread-local database connection
            db = Database(self.db_path)
            db.initialize_schema()

            # Get all bookmarks
            bookmarks = Bookmark.get_all(db)
            db.close()  # Close DB connection early - we don't need it anymore

            # Filter to only HTTP/HTTPS URLs
            http_bookmarks = [
                b for b in bookmarks
                if b.url.startswith(('http://', 'https://'))
            ]
            total = len(http_bookmarks)

            if total == 0:
                self.finished_checking.emit([])
                return

            dead_links = []
            checked_count = 0
            progress = CheckProgress(total=total)

            # Use ThreadPoolExecutor for parallel URL checking
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all URL checks
                future_to_bookmark = {
                    executor.submit(
                        check_single_url,
                        bookmark.url,
                        self.timeout,
                        self.check_ssl
                    ): bookmark
                    for bookmark in http_bookmarks
                }

                # Process results as they complete
                for future in as_completed(future_to_bookmark):
                    if self._cancelled:
                        # Cancel remaining futures
                        for f in future_to_bookmark:
                            f.cancel()
                        break

                    bookmark = future_to_bookmark[future]
                    checked_count += 1

                    try:
                        is_dead, status_code, error_message = future.result()
                    except Exception as e:
                        is_dead = True
                        status_code = None
                        error_message = f"Error: {str(e)}"

                    result = DeadLinkResult(
                        bookmark_id=bookmark.bookmark_id,
                        title=bookmark.title or "(No title)",
                        url=bookmark.url,
                        status_code=status_code,
                        error_message=error_message,
                        is_dead=is_dead
                    )

                    self.link_checked.emit(result)

                    if is_dead:
                        dead_links.append(result)

                    # Update progress
                    progress.current = checked_count
                    progress.checked_count = checked_count
                    progress.current_url = bookmark.url
                    progress.current_title = bookmark.title or "(No title)"
                    progress.dead_count = len(dead_links)
                    self.progress_updated.emit(progress)

            self.finished_checking.emit(dead_links)

        except Exception as e:
            self.error_occurred.emit(str(e))


class DeadLinkDialog(QDialog):
    """Dialog for checking dead links with progress display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_database()
        self.worker = None
        self.dead_links = []

        self.setWindowTitle("Dead Link Checker")
        self.setMinimumSize(700, 500)
        self.setup_ui()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Options group
        options_group = QGroupBox("Options")
        options_layout = QHBoxLayout(options_group)

        options_layout.addWidget(QLabel("Timeout (seconds):"))
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 60)
        self.timeout_spin.setValue(10)
        options_layout.addWidget(self.timeout_spin)

        options_layout.addSpacing(20)

        options_layout.addWidget(QLabel("Parallel checks:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 20)
        self.workers_spin.setValue(10)
        self.workers_spin.setToolTip("Number of URLs to check simultaneously")
        options_layout.addWidget(self.workers_spin)

        options_layout.addSpacing(20)

        self.ssl_check = QCheckBox("Verify SSL Certificates")
        self.ssl_check.setChecked(True)
        options_layout.addWidget(self.ssl_check)

        options_layout.addStretch()
        layout.addWidget(options_group)

        # Progress group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        # Current item being checked
        self.current_label = QLabel("Ready to start...")
        self.current_label.setWordWrap(True)
        progress_layout.addWidget(self.current_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        # Stats
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("Checked: 0 / 0  |  Dead links found: 0")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        progress_layout.addLayout(stats_layout)

        layout.addWidget(progress_group)

        # Results table
        results_group = QGroupBox("Dead Links Found")
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Title", "URL", "Status", "Error"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setAlternatingRowColors(True)
        results_layout.addWidget(self.results_table)

        layout.addWidget(results_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.start_button = QPushButton("Start Check")
        self.start_button.clicked.connect(self.start_check)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_check)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def start_check(self):
        """Start the dead link check."""
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.timeout_spin.setEnabled(False)
        self.workers_spin.setEnabled(False)
        self.ssl_check.setEnabled(False)
        self.results_table.setRowCount(0)
        self.dead_links = []

        self.current_label.setText("Starting check...")
        self.progress_bar.setValue(0)

        # Create and start worker - use db_path from the database instance
        self.worker = DeadLinkWorker(
            self.db.db_path,
            timeout=self.timeout_spin.value(),
            check_ssl=self.ssl_check.isChecked(),
            max_workers=self.workers_spin.value()
        )
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.link_checked.connect(self.on_link_checked)
        self.worker.finished_checking.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def cancel_check(self):
        """Cancel the current check."""
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.current_label.setText("Cancelling...")

    def on_progress_updated(self, progress: CheckProgress):
        """Handle progress updates."""
        if progress.total > 0:
            percent = int((progress.current / progress.total) * 100)
            self.progress_bar.setValue(percent)

        # Truncate long URLs for display
        url_display = progress.current_url
        if len(url_display) > 60:
            url_display = url_display[:57] + "..."

        self.current_label.setText(f"Checking: {progress.current_title}\n{url_display}")
        self.stats_label.setText(
            f"Checked: {progress.checked_count} / {progress.total}  |  "
            f"Dead links found: {progress.dead_count}"
        )

    def on_link_checked(self, result: DeadLinkResult):
        """Handle a single link check result."""
        if result.is_dead:
            self.dead_links.append(result)

            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            self.results_table.setItem(row, 0, QTableWidgetItem(result.title))
            self.results_table.setItem(row, 1, QTableWidgetItem(result.url))

            status_text = str(result.status_code) if result.status_code else "N/A"
            self.results_table.setItem(row, 2, QTableWidgetItem(status_text))

            error_text = result.error_message or ""
            self.results_table.setItem(row, 3, QTableWidgetItem(error_text))

    def on_finished(self, dead_links: list):
        """Handle check completion."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.timeout_spin.setEnabled(True)
        self.workers_spin.setEnabled(True)
        self.ssl_check.setEnabled(True)

        self.progress_bar.setValue(100)

        count = len(dead_links)
        if count == 0:
            self.current_label.setText("Check complete! No dead links found.")
            QMessageBox.information(
                self, "Check Complete",
                "No dead links were found in your bookmarks."
            )
        else:
            self.current_label.setText(f"Check complete! Found {count} dead link(s).")
            QMessageBox.warning(
                self, "Check Complete",
                f"Found {count} dead link(s) in your bookmarks.\n\n"
                "Review the results table below."
            )

    def on_error(self, error_message: str):
        """Handle errors during check."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.timeout_spin.setEnabled(True)
        self.workers_spin.setEnabled(True)
        self.ssl_check.setEnabled(True)

        self.current_label.setText(f"Error: {error_message}")
        QMessageBox.critical(self, "Error", f"An error occurred:\n\n{error_message}")

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)  # Wait up to 2 seconds
        event.accept()
