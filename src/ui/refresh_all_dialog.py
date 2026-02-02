"""Refresh All Dialog - Runs backup, import, duplicate check, and dead link check."""

import os
import shutil
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QCheckBox, QGroupBox, QTextEdit, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from ..models.database import Database, get_database, reset_database
from ..models.bookmark import Bookmark
from ..services.profile_detector import ProfileDetector
from ..services.import_service import ImportService, ImportProgress
from .duplicate_dialog import normalize_url, DuplicateGroup
from .dead_link_dialog import check_single_url
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid


class RefreshAllWorker(QThread):
    """Worker thread that runs all refresh operations."""

    status_updated = pyqtSignal(str)  # Status message
    progress_updated = pyqtSignal(int, int, str)  # current, total, phase
    overall_progress = pyqtSignal(int, int, str)  # completed_phases, total_phases, current_phase_name
    phase_completed = pyqtSignal(str, str)  # phase name, result summary
    all_completed = pyqtSignal(dict)  # Summary of all results
    error_occurred = pyqtSignal(str)

    def __init__(self, db_path: str, do_backup: bool, do_import: bool,
                 do_duplicates: bool, do_dead_links: bool, start_fresh: bool):
        super().__init__()
        self.db_path = db_path
        self.do_backup = do_backup
        self.do_import = do_import
        self.do_duplicates = do_duplicates
        self.do_dead_links = do_dead_links
        self.start_fresh = start_fresh
        self._cancelled = False

        # Calculate total phases for overall progress
        self.total_phases = sum([
            1 if do_backup else 0,
            1 if do_import else 0,
            1 if do_duplicates else 0,
            1 if do_dead_links else 0
        ])
        self.completed_phases = 0

    def cancel(self):
        """Request cancellation."""
        self._cancelled = True

    def run(self):
        """Run all selected operations."""
        results = {
            'backup': None,
            'import': None,
            'duplicates': None,
            'dead_links': None
        }

        try:
            # Phase 1: Backup and optionally create fresh database
            if self.do_backup and not self._cancelled:
                self.overall_progress.emit(self.completed_phases, self.total_phases, "Backup")
                self.status_updated.emit("Creating database backup...")
                self.progress_updated.emit(0, 1, "Backup")
                backup_path = self.create_backup()
                results['backup'] = backup_path
                self.progress_updated.emit(1, 1, "Backup")
                self.phase_completed.emit("Backup", f"Created: {backup_path}")

                if self.start_fresh:
                    self.status_updated.emit("Creating fresh database...")
                    self.create_fresh_database()
                    self.phase_completed.emit("Fresh DB", "New database created")

                self.completed_phases += 1

            # Phase 2: Import
            if self.do_import and not self._cancelled:
                self.overall_progress.emit(self.completed_phases, self.total_phases, "Import")
                self.status_updated.emit("Importing bookmarks from browsers...")
                import_result = self.run_import()
                results['import'] = import_result
                self.phase_completed.emit("Import", import_result)
                self.completed_phases += 1

            # Phase 3: Duplicates
            if self.do_duplicates and not self._cancelled:
                self.overall_progress.emit(self.completed_phases, self.total_phases, "Duplicates")
                self.status_updated.emit("Finding duplicates...")
                dup_result = self.find_duplicates()
                results['duplicates'] = dup_result
                self.phase_completed.emit("Duplicates", dup_result)
                self.completed_phases += 1

            # Phase 4: Dead Links
            if self.do_dead_links and not self._cancelled:
                self.overall_progress.emit(self.completed_phases, self.total_phases, "Dead Links")
                self.status_updated.emit("Checking for dead links...")
                dead_result = self.check_dead_links()
                results['dead_links'] = dead_result
                self.phase_completed.emit("Dead Links", dead_result)
                self.completed_phases += 1

            # Final overall progress
            self.overall_progress.emit(self.total_phases, self.total_phases, "Complete")
            self.all_completed.emit(results)

        except Exception as e:
            self.error_occurred.emit(str(e))

    def create_backup(self) -> str:
        """Create a timestamped backup of the database."""
        db_path = Path(self.db_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"bookmarks_backup_{timestamp}.db"
        backup_path = db_path.parent / backup_name

        shutil.copy2(db_path, backup_path)
        return str(backup_path)

    def create_fresh_database(self):
        """Delete the current database and create a fresh one."""
        db_path = Path(self.db_path)

        # Remove the existing database file
        if db_path.exists():
            os.remove(db_path)

        # Create a new database with fresh schema
        db = Database(self.db_path)
        db.initialize_schema()
        db.close()

    def run_import(self) -> str:
        """Import bookmarks from all detected browser profiles."""
        db = Database(self.db_path)
        db.initialize_schema()

        detector = ProfileDetector()
        profiles = detector.detect_all_profiles()

        if not profiles:
            db.close()
            return "No browser profiles found"

        # Filter to only profiles with bookmarks
        profiles_with_bookmarks = [p for p in profiles if p.has_bookmarks_file]

        if not profiles_with_bookmarks:
            db.close()
            return "No profiles with bookmarks found"

        self.status_updated.emit(f"Importing from {len(profiles_with_bookmarks)} profiles...")
        self.progress_updated.emit(0, 100, "Importing")

        import_service = ImportService(db)
        total_imported = 0
        total_skipped = 0
        profiles_processed = 0

        # We'll track progress using the actual totals from ImportProgress
        # which includes both folders and bookmarks
        cumulative_items = 0
        cumulative_total = 0

        for profile in profiles_with_bookmarks:
            if self._cancelled:
                break

            profile_name = profile.profile_name or profile.profile_id

            # Create progress callback that uses the actual item counts from import
            def progress_callback(progress: ImportProgress,
                                  base_items=cumulative_items,
                                  base_total=cumulative_total,
                                  browser=profile.browser_name,
                                  pname=profile_name):
                if self._cancelled:
                    return
                # Use progress.total_items which includes folders + bookmarks for this profile
                current = base_items + progress.current_item
                # Estimate total based on what we've seen so far
                estimated_total = base_total + progress.total_items
                title = (progress.current_title or "(no title)")[:50]
                status_msg = f"Importing {browser}/{pname}: {title}"
                self.status_updated.emit(status_msg)
                self.progress_updated.emit(current, estimated_total, "Importing")

            try:
                result = import_service.import_profile(profile, progress_callback)
                total_imported += result.bookmarks_added
                total_skipped += result.bookmarks_skipped
                profiles_processed += 1
                # Get the actual count of items processed for this profile
                # (folders_added + folders_skipped + bookmarks_added + bookmarks_skipped)
                profile_items = (result.folders_added + result.folders_skipped +
                                result.bookmarks_added + result.bookmarks_skipped)
                cumulative_items += profile_items
                cumulative_total += profile_items
            except Exception as e:
                # Continue with other profiles
                pass

        self.progress_updated.emit(cumulative_items, cumulative_items, "Importing")
        db.close()
        return f"Imported {total_imported} new bookmarks from {profiles_processed} profiles ({total_skipped} skipped)"

    def find_duplicates(self) -> str:
        """Find duplicate bookmarks."""
        check_run_id = str(uuid.uuid4())[:8]

        db = Database(self.db_path)
        db.initialize_schema()

        bookmarks = Bookmark.get_all(db)

        if not bookmarks:
            db.close()
            return "No bookmarks to check"

        total_bookmarks = len(bookmarks)
        self.status_updated.emit(f"Analyzing {total_bookmarks} bookmarks for duplicates...")
        self.progress_updated.emit(0, total_bookmarks, "Analyzing URLs")

        # Group by normalized URL
        url_to_bookmarks = {}
        for i, bookmark in enumerate(bookmarks):
            if self._cancelled:
                db.close()
                return "Cancelled"

            normalized = normalize_url(bookmark.url)
            if normalized not in url_to_bookmarks:
                url_to_bookmarks[normalized] = []
            url_to_bookmarks[normalized].append(bookmark)

            # Update progress every 100 bookmarks
            if i % 100 == 0:
                title = bookmark.title[:50] if bookmark.title else "(no title)"
                self.status_updated.emit(f"Analyzing: {title}")
                self.progress_updated.emit(i, total_bookmarks, "Analyzing URLs")

        # Find duplicates
        exact_groups = 0
        exact_bookmarks = 0
        unique_urls = list(url_to_bookmarks.items())
        total_urls = len(unique_urls)

        self.status_updated.emit(f"Checking {total_urls} unique URLs for duplicates...")
        self.progress_updated.emit(0, total_urls, "Finding duplicates")

        for i, (normalized_url, group_bookmarks) in enumerate(unique_urls):
            if self._cancelled:
                break

            if len(group_bookmarks) > 1:
                exact_groups += 1
                exact_bookmarks += len(group_bookmarks)

                # Save to database
                cursor = db.execute("""
                    INSERT INTO duplicate_groups (check_run_id, normalized_url, match_type, similarity)
                    VALUES (?, ?, ?, ?)
                """, (check_run_id, normalized_url, "exact", 1.0))
                group_id = cursor.lastrowid

                for bookmark in group_bookmarks:
                    db.execute("""
                        INSERT INTO duplicate_group_members (duplicate_group_id, bookmark_id)
                        VALUES (?, ?)
                    """, (group_id, bookmark.bookmark_id))

            # Update progress every 50 URLs
            if i % 50 == 0:
                self.status_updated.emit(f"Processing duplicates: {i}/{total_urls} URLs...")
                self.progress_updated.emit(i, total_urls, "Finding duplicates")

        self.progress_updated.emit(total_urls, total_urls, "Finding duplicates")
        db.commit()
        db.close()

        return f"Found {exact_bookmarks} duplicates in {exact_groups} groups (Run ID: {check_run_id})"

    def check_dead_links(self) -> str:
        """Check for dead links."""
        check_run_id = str(uuid.uuid4())[:8]

        db = Database(self.db_path)
        db.initialize_schema()

        bookmarks = Bookmark.get_all(db)

        # Filter to HTTP/HTTPS URLs
        http_bookmarks = [b for b in bookmarks if b.url.startswith(('http://', 'https://'))]

        if not http_bookmarks:
            db.close()
            return "No URLs to check"

        # Group by normalized URL
        url_to_bookmarks = {}
        for bookmark in http_bookmarks:
            normalized = normalize_url(bookmark.url)
            if normalized not in url_to_bookmarks:
                url_to_bookmarks[normalized] = []
            url_to_bookmarks[normalized].append(bookmark)

        unique_urls = len(url_to_bookmarks)
        dead_count = 0
        checked = 0

        self.status_updated.emit(f"Checking {unique_urls} unique URLs for dead links...")
        self.progress_updated.emit(0, unique_urls, "Checking URLs")

        # Check URLs in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_normalized = {}
            for normalized_url, bookmark_group in url_to_bookmarks.items():
                actual_url = bookmark_group[0].url
                future = executor.submit(check_single_url, actual_url, 10, True)
                future_to_normalized[future] = (normalized_url, bookmark_group)

            for future in as_completed(future_to_normalized):
                if self._cancelled:
                    break

                normalized_url, bookmark_group = future_to_normalized[future]
                checked += 1

                # Show progress with URL being checked
                url_display = bookmark_group[0].url[:60]
                self.status_updated.emit(f"Checking ({checked}/{unique_urls}): {url_display}")
                self.progress_updated.emit(checked, unique_urls, "Checking URLs")

                try:
                    is_dead, status_code, error_message = future.result()
                except Exception as e:
                    is_dead = True
                    status_code = None
                    error_message = str(e)

                if is_dead:
                    dead_count += len(bookmark_group)
                    for bookmark in bookmark_group:
                        db.execute("""
                            INSERT INTO dead_links (bookmark_id, check_run_id, status_code, error_message)
                            VALUES (?, ?, ?, ?)
                        """, (bookmark.bookmark_id, check_run_id, status_code, error_message))

        db.commit()
        db.close()

        return f"Found {dead_count} dead links (checked {unique_urls} unique URLs, Run ID: {check_run_id})"


class RefreshAllDialog(QDialog):
    """Dialog for running all refresh operations."""

    # Signal to notify parent that database was reset
    database_reset = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_database()
        self.worker = None

        self.setWindowTitle("Refresh All")
        self.setMinimumSize(550, 500)
        self.setup_ui()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Description
        desc_label = QLabel(
            "Run multiple maintenance operations in sequence.\n"
            "Select the operations you want to perform:"
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Options group
        options_group = QGroupBox("Operations")
        options_layout = QVBoxLayout(options_group)

        self.backup_check = QCheckBox("1. Backup database (with timestamp)")
        self.backup_check.setChecked(True)
        options_layout.addWidget(self.backup_check)

        # Sub-option for starting fresh
        self.fresh_db_check = QCheckBox("    Start with fresh database after backup")
        self.fresh_db_check.setChecked(True)
        self.fresh_db_check.setToolTip(
            "Delete the current database after backup and start fresh.\n"
            "This ensures a clean import without old/stale data."
        )
        options_layout.addWidget(self.fresh_db_check)

        # Connect backup checkbox to enable/disable fresh db option
        self.backup_check.stateChanged.connect(self.on_backup_changed)

        self.import_check = QCheckBox("2. Import bookmarks from browsers")
        self.import_check.setChecked(True)
        options_layout.addWidget(self.import_check)

        self.duplicates_check = QCheckBox("3. Find duplicate bookmarks")
        self.duplicates_check.setChecked(True)
        options_layout.addWidget(self.duplicates_check)

        self.dead_links_check = QCheckBox("4. Check for dead links")
        self.dead_links_check.setChecked(True)
        options_layout.addWidget(self.dead_links_check)

        layout.addWidget(options_group)

        # Progress group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        # Current phase progress (at top)
        self.phase_label = QLabel("Current phase:")
        progress_layout.addWidget(self.phase_label)

        self.status_label = QLabel("Ready to start...")
        progress_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        # Spacer
        progress_layout.addSpacing(10)

        # Overall progress (at bottom)
        overall_label = QLabel("Overall:")
        progress_layout.addWidget(overall_label)

        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setMinimum(0)
        self.overall_progress_bar.setMaximum(100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFormat("%p% - %v/%m phases")
        progress_layout.addWidget(self.overall_progress_bar)

        layout.addWidget(progress_group)

        # Log output
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

        # Buttons
        button_layout = QHBoxLayout()

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_refresh)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_refresh)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def on_backup_changed(self, state):
        """Handle backup checkbox state change."""
        self.fresh_db_check.setEnabled(state == Qt.CheckState.Checked.value)
        if state != Qt.CheckState.Checked.value:
            self.fresh_db_check.setChecked(False)

    def start_refresh(self):
        """Start the refresh operations."""
        # Check at least one option is selected
        if not any([
            self.backup_check.isChecked(),
            self.import_check.isChecked(),
            self.duplicates_check.isChecked(),
            self.dead_links_check.isChecked()
        ]):
            QMessageBox.warning(self, "No Operations Selected",
                              "Please select at least one operation to perform.")
            return

        # Warn if starting fresh without import
        if self.fresh_db_check.isChecked() and not self.import_check.isChecked():
            reply = QMessageBox.warning(
                self, "Warning",
                "You selected 'Start with fresh database' but did not select 'Import bookmarks'.\n\n"
                "This will result in an empty database!\n\n"
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.backup_check.setEnabled(False)
        self.fresh_db_check.setEnabled(False)
        self.import_check.setEnabled(False)
        self.duplicates_check.setEnabled(False)
        self.dead_links_check.setEnabled(False)

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.overall_progress_bar.setValue(0)
        self.status_label.setText("Starting...")
        self.phase_label.setText("Current phase: Starting...")

        # Reset the global database instance so worker creates fresh connection
        reset_database()

        self.worker = RefreshAllWorker(
            str(self.db.db_path),  # Pass path, not the closed connection
            self.backup_check.isChecked(),
            self.import_check.isChecked(),
            self.duplicates_check.isChecked(),
            self.dead_links_check.isChecked(),
            self.fresh_db_check.isChecked() and self.backup_check.isChecked()
        )
        self.worker.status_updated.connect(self.on_status_updated)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.overall_progress.connect(self.on_overall_progress)
        self.worker.phase_completed.connect(self.on_phase_completed)
        self.worker.all_completed.connect(self.on_all_completed)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def cancel_refresh(self):
        """Cancel the refresh operations."""
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def on_status_updated(self, status: str):
        """Handle status updates."""
        self.status_label.setText(status)

    def on_progress_updated(self, current: int, total: int, phase: str):
        """Handle progress updates for current phase."""
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{phase}: %p% ({current}/{total})")

    def on_overall_progress(self, completed: int, total: int, phase_name: str):
        """Handle overall progress updates."""
        if total > 0:
            # Set the overall progress bar to show phases
            self.overall_progress_bar.setMaximum(total)
            self.overall_progress_bar.setValue(completed)
            self.overall_progress_bar.setFormat(f"%v/%m phases complete")
            self.phase_label.setText(f"Current phase: {phase_name}")
            # Reset the phase progress bar when starting a new phase
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(f"{phase_name}: 0%")

    def on_phase_completed(self, phase: str, result: str):
        """Handle phase completion."""
        self.log_text.append(f"[{phase}] {result}")

    def on_all_completed(self, results: dict):
        """Handle all operations completed."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.backup_check.setEnabled(True)
        self.fresh_db_check.setEnabled(self.backup_check.isChecked())
        self.import_check.setEnabled(True)
        self.duplicates_check.setEnabled(True)
        self.dead_links_check.setEnabled(True)

        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("Complete: 100%")
        self.overall_progress_bar.setValue(self.overall_progress_bar.maximum())
        self.overall_progress_bar.setFormat("All phases complete!")
        self.phase_label.setText("Current phase: Complete")
        self.status_label.setText("All operations completed!")

        self.log_text.append("\n--- All operations completed ---")

        # Emit signal so parent can reset its database connection
        self.database_reset.emit()

        QMessageBox.information(self, "Refresh Complete",
                              "All selected operations have been completed.\n\n"
                              "Review the log for details.")

    def on_error(self, error_message: str):
        """Handle errors."""
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.backup_check.setEnabled(True)
        self.fresh_db_check.setEnabled(self.backup_check.isChecked())
        self.import_check.setEnabled(True)
        self.duplicates_check.setEnabled(True)
        self.dead_links_check.setEnabled(True)

        self.status_label.setText(f"Error: {error_message}")
        self.log_text.append(f"\n[ERROR] {error_message}")

        QMessageBox.critical(self, "Error", f"An error occurred:\n\n{error_message}")

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        event.accept()
