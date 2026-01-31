"""Duplicate Bookmark Detection Dialog."""

import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs, urlencode
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSpinBox, QTabWidget, QWidget, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from ..models.database import Database, get_database
from ..models.bookmark import Bookmark


@dataclass
class DuplicateGroup:
    """A group of duplicate bookmarks."""
    canonical_url: str  # The normalized URL used for grouping
    bookmarks: list  # List of Bookmark objects
    match_type: str  # "exact" or "similar"
    similarity: float = 1.0  # For similar matches, how similar (0-1)


def normalize_url(url: str) -> str:
    """
    Normalize a URL for exact duplicate detection.
    - Removes trailing slashes
    - Lowercases the domain
    - Sorts query parameters
    - Removes common tracking parameters
    """
    try:
        parsed = urlparse(url.strip())

        # Lowercase the netloc (domain)
        netloc = parsed.netloc.lower()

        # Remove www. prefix for comparison
        if netloc.startswith('www.'):
            netloc = netloc[4:]

        # Normalize path - remove trailing slash
        path = parsed.path.rstrip('/') or '/'

        # Parse and sort query parameters, removing tracking params
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'ref', 'source', 'mc_cid', 'mc_eid'
        }

        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            # Remove tracking parameters
            filtered_params = {k: v for k, v in params.items() if k.lower() not in tracking_params}
            # Sort and rebuild query string
            sorted_query = urlencode(sorted(filtered_params.items()), doseq=True)
        else:
            sorted_query = ''

        # Rebuild URL without fragment
        normalized = f"{parsed.scheme}://{netloc}{path}"
        if sorted_query:
            normalized += f"?{sorted_query}"

        return normalized
    except Exception:
        return url.strip().lower()


def get_url_signature(url: str) -> str:
    """
    Get a simplified signature for fuzzy matching.
    Strips protocol, www, trailing slashes, and query strings.
    """
    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        path = parsed.path.rstrip('/') or '/'
        return f"{netloc}{path}"
    except Exception:
        return url.strip().lower()


def url_similarity(url1: str, url2: str) -> float:
    """Calculate similarity between two URLs (0-1)."""
    sig1 = get_url_signature(url1)
    sig2 = get_url_signature(url2)
    return SequenceMatcher(None, sig1, sig2).ratio()


class DuplicateFinderWorker(QThread):
    """Worker thread to find duplicate bookmarks."""

    progress_updated = pyqtSignal(int, int, str)  # current, total, status
    exact_duplicates_found = pyqtSignal(list, str)  # List of DuplicateGroup, check_run_id
    similar_duplicates_found = pyqtSignal(list, str)  # List of DuplicateGroup, check_run_id
    finished_checking = pyqtSignal(str)  # check_run_id
    error_occurred = pyqtSignal(str)

    def __init__(self, db_path: str, similarity_threshold: float = 0.85):
        super().__init__()
        self.db_path = db_path
        self.similarity_threshold = similarity_threshold
        self._cancelled = False

    def cancel(self):
        """Request cancellation."""
        self._cancelled = True

    def run(self):
        """Find duplicates."""
        try:
            # Generate unique run ID for this check
            check_run_id = str(uuid.uuid4())[:8]

            # Create thread-local database connection
            db = Database(self.db_path)
            db.initialize_schema()

            # Get all bookmarks
            bookmarks = Bookmark.get_all(db)

            total = len(bookmarks)
            if total == 0:
                self.exact_duplicates_found.emit([], check_run_id)
                self.similar_duplicates_found.emit([], check_run_id)
                self.finished_checking.emit(check_run_id)
                db.close()
                return

            # Phase 1: Find exact duplicates (by normalized URL)
            self.progress_updated.emit(0, total, "Finding exact duplicates...")

            url_to_bookmarks = {}
            for i, bookmark in enumerate(bookmarks):
                if self._cancelled:
                    db.close()
                    return

                normalized = normalize_url(bookmark.url)
                if normalized not in url_to_bookmarks:
                    url_to_bookmarks[normalized] = []
                url_to_bookmarks[normalized].append(bookmark)

                if i % 100 == 0:
                    self.progress_updated.emit(i, total, "Finding exact duplicates...")

            # Filter to only groups with duplicates and save to database
            exact_groups = []
            for normalized_url, group_bookmarks in url_to_bookmarks.items():
                if len(group_bookmarks) > 1:
                    group = DuplicateGroup(
                        canonical_url=normalized_url,
                        bookmarks=group_bookmarks,
                        match_type="exact",
                        similarity=1.0
                    )
                    exact_groups.append(group)

                    # Save to database
                    cursor = db.execute("""
                        INSERT INTO duplicate_groups (check_run_id, normalized_url, match_type, similarity)
                        VALUES (?, ?, ?, ?)
                    """, (check_run_id, normalized_url, "exact", 1.0))
                    group_id = cursor.lastrowid

                    # Save group members
                    for bookmark in group_bookmarks:
                        db.execute("""
                            INSERT INTO duplicate_group_members (duplicate_group_id, bookmark_id)
                            VALUES (?, ?)
                        """, (group_id, bookmark.bookmark_id))

            db.commit()
            self.exact_duplicates_found.emit(exact_groups, check_run_id)

            # Phase 2: Find similar URLs (fuzzy matching)
            # Only compare unique normalized URLs to avoid redundant comparisons
            self.progress_updated.emit(0, len(url_to_bookmarks), "Finding similar URLs...")

            unique_urls = list(url_to_bookmarks.keys())
            similar_groups = []
            processed_pairs = set()

            for i, url1 in enumerate(unique_urls):
                if self._cancelled:
                    db.close()
                    return

                if i % 10 == 0:
                    self.progress_updated.emit(i, len(unique_urls), "Finding similar URLs...")

                for j, url2 in enumerate(unique_urls[i+1:], i+1):
                    pair_key = (min(url1, url2), max(url1, url2))
                    if pair_key in processed_pairs:
                        continue
                    processed_pairs.add(pair_key)

                    similarity = url_similarity(url1, url2)
                    if similarity >= self.similarity_threshold and similarity < 1.0:
                        # Combine bookmarks from both URLs
                        combined_bookmarks = url_to_bookmarks[url1] + url_to_bookmarks[url2]
                        group = DuplicateGroup(
                            canonical_url=f"{url1} <-> {url2}",
                            bookmarks=combined_bookmarks,
                            match_type="similar",
                            similarity=similarity
                        )
                        similar_groups.append(group)

                        # Save to database
                        cursor = db.execute("""
                            INSERT INTO duplicate_groups (check_run_id, normalized_url, match_type, similarity)
                            VALUES (?, ?, ?, ?)
                        """, (check_run_id, f"{url1} <-> {url2}", "similar", similarity))
                        group_id = cursor.lastrowid

                        # Save group members
                        for bookmark in combined_bookmarks:
                            db.execute("""
                                INSERT INTO duplicate_group_members (duplicate_group_id, bookmark_id)
                                VALUES (?, ?)
                            """, (group_id, bookmark.bookmark_id))

            db.commit()
            self.similar_duplicates_found.emit(similar_groups, check_run_id)
            self.progress_updated.emit(total, total, "Complete!")
            self.finished_checking.emit(check_run_id)
            db.close()

        except Exception as e:
            self.error_occurred.emit(str(e))


class DuplicateDialog(QDialog):
    """Dialog for finding and displaying duplicate bookmarks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_database()
        self.worker = None
        self.exact_groups = []
        self.similar_groups = []
        self.check_run_id = None

        self.setWindowTitle("Duplicate Bookmark Finder")
        self.setMinimumSize(900, 600)
        self.setup_ui()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Options group
        options_group = QGroupBox("Options")
        options_layout = QHBoxLayout(options_group)

        options_layout.addWidget(QLabel("Similarity threshold (%):"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(70, 99)
        self.threshold_spin.setValue(85)
        self.threshold_spin.setToolTip("URLs with similarity above this threshold are considered similar")
        options_layout.addWidget(self.threshold_spin)

        options_layout.addStretch()
        layout.addWidget(options_group)

        # Progress group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.status_label = QLabel("Ready to start...")
        progress_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # Results tabs
        self.tab_widget = QTabWidget()

        # Exact duplicates tab
        exact_widget = QWidget()
        exact_layout = QVBoxLayout(exact_widget)
        self.exact_table = QTableWidget()
        self.exact_table.setColumnCount(5)
        self.exact_table.setHorizontalHeaderLabels(["Title", "URL", "Folder", "Profile", "Group Size"])
        # All columns interactive (resizable) except URL which stretches
        self.exact_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.exact_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.exact_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.exact_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.exact_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.exact_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.exact_table.setAlternatingRowColors(True)
        self.exact_table.setColumnWidth(0, 200)
        self.exact_table.setColumnWidth(2, 120)
        self.exact_table.setColumnWidth(3, 150)
        self.exact_table.setColumnWidth(4, 70)
        exact_layout.addWidget(self.exact_table)
        self.tab_widget.addTab(exact_widget, "Exact Duplicates (0)")

        # Similar URLs tab
        similar_widget = QWidget()
        similar_layout = QVBoxLayout(similar_widget)
        self.similar_table = QTableWidget()
        self.similar_table.setColumnCount(5)
        self.similar_table.setHorizontalHeaderLabels(["Title", "URL", "Folder", "Profile", "Similarity"])
        # All columns interactive (resizable) except URL which stretches
        self.similar_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.similar_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.similar_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.similar_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.similar_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.similar_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.similar_table.setAlternatingRowColors(True)
        self.similar_table.setColumnWidth(0, 200)
        self.similar_table.setColumnWidth(2, 120)
        self.similar_table.setColumnWidth(3, 150)
        self.similar_table.setColumnWidth(4, 70)
        similar_layout.addWidget(self.similar_table)
        self.tab_widget.addTab(similar_widget, "Similar URLs (0)")

        layout.addWidget(self.tab_widget)

        # Buttons
        button_layout = QHBoxLayout()

        self.start_button = QPushButton("Find Duplicates")
        self.start_button.clicked.connect(self.start_search)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_search)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def start_search(self):
        """Start the duplicate search."""
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.threshold_spin.setEnabled(False)
        self.exact_table.setRowCount(0)
        self.similar_table.setRowCount(0)
        self.exact_groups = []
        self.similar_groups = []
        self.check_run_id = None

        self.status_label.setText("Starting search...")
        self.progress_bar.setValue(0)

        # Create and start worker
        self.worker = DuplicateFinderWorker(
            self.db.db_path,
            similarity_threshold=self.threshold_spin.value() / 100.0
        )
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.exact_duplicates_found.connect(self.on_exact_found)
        self.worker.similar_duplicates_found.connect(self.on_similar_found)
        self.worker.finished_checking.connect(self.on_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def cancel_search(self):
        """Cancel the search."""
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def on_progress_updated(self, current: int, total: int, status: str):
        """Handle progress updates."""
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
        self.status_label.setText(status)

    def on_exact_found(self, groups: list, check_run_id: str):
        """Handle exact duplicates found."""
        self.exact_groups = groups
        self.check_run_id = check_run_id

        # Count total duplicate bookmarks (not groups)
        total_duplicates = sum(len(g.bookmarks) for g in groups)
        self.tab_widget.setTabText(0, f"Exact Duplicates ({total_duplicates})")

        # Populate table - show each bookmark in duplicate groups
        for group in groups:
            for bookmark in group.bookmarks:
                row = self.exact_table.rowCount()
                self.exact_table.insertRow(row)

                self.exact_table.setItem(row, 0, QTableWidgetItem(bookmark.title or "(no title)"))
                self.exact_table.setItem(row, 1, QTableWidgetItem(bookmark.url))
                self.exact_table.setItem(row, 2, QTableWidgetItem(""))  # TODO: folder name
                self.exact_table.setItem(row, 3, QTableWidgetItem(""))  # TODO: profile name
                self.exact_table.setItem(row, 4, QTableWidgetItem(str(len(group.bookmarks))))

    def on_similar_found(self, groups: list, check_run_id: str):
        """Handle similar URLs found."""
        self.similar_groups = groups

        total_similar = sum(len(g.bookmarks) for g in groups)
        self.tab_widget.setTabText(1, f"Similar URLs ({total_similar})")

        # Populate table
        for group in groups:
            for bookmark in group.bookmarks:
                row = self.similar_table.rowCount()
                self.similar_table.insertRow(row)

                self.similar_table.setItem(row, 0, QTableWidgetItem(bookmark.title or "(no title)"))
                self.similar_table.setItem(row, 1, QTableWidgetItem(bookmark.url))
                self.similar_table.setItem(row, 2, QTableWidgetItem(""))  # TODO: folder name
                self.similar_table.setItem(row, 3, QTableWidgetItem(""))  # TODO: profile name
                self.similar_table.setItem(row, 4, QTableWidgetItem(f"{group.similarity:.0%}"))

    def on_finished(self, check_run_id: str):
        """Handle search completion."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.threshold_spin.setEnabled(True)
        self.check_run_id = check_run_id

        self.progress_bar.setValue(100)

        exact_count = sum(len(g.bookmarks) for g in self.exact_groups)
        similar_count = sum(len(g.bookmarks) for g in self.similar_groups)

        if exact_count == 0 and similar_count == 0:
            self.status_label.setText("Complete! No duplicate bookmarks were found.")
            QMessageBox.information(
                self, "Search Complete",
                "No duplicate bookmarks were found."
            )
        else:
            self.status_label.setText(
                f"Complete! Found {exact_count} exact duplicates in {len(self.exact_groups)} groups, "
                f"{similar_count} similar URLs in {len(self.similar_groups)} groups.\n"
                f"Run ID: {check_run_id}. Results saved to database."
            )
            QMessageBox.information(
                self, "Search Complete",
                f"Found {exact_count} exact duplicates in {len(self.exact_groups)} groups.\n"
                f"Found {similar_count} similar URLs in {len(self.similar_groups)} groups.\n\n"
                f"Results saved to database (Run ID: {check_run_id})."
            )

    def on_error(self, error_message: str):
        """Handle errors."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.threshold_spin.setEnabled(True)

        self.status_label.setText(f"Error: {error_message}")
        QMessageBox.critical(self, "Error", f"An error occurred:\n\n{error_message}")

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        event.accept()


# Export the normalize_url function for use by dead link checker
__all__ = ['DuplicateDialog', 'normalize_url', 'DuplicateGroup']
