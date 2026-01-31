"""Import dialog with progress bar for importing bookmarks from browsers."""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QGroupBox,
    QCheckBox,
    QScrollArea,
    QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ..models.database import Database
from ..services.import_service import ImportService, ImportProgress, ImportResult
from ..services.profile_detector import ProfileDetector, DetectedProfile


class ImportWorker(QThread):
    """Worker thread to run import without blocking the UI."""

    # Signals to communicate with the main thread
    progress_updated = pyqtSignal(object)  # ImportProgress
    profile_started = pyqtSignal(str, str)  # browser_name, profile_name
    profile_finished = pyqtSignal(object)  # ImportResult
    import_finished = pyqtSignal(list)  # List[ImportResult]
    error_occurred = pyqtSignal(str)

    def __init__(self, profiles_to_import: list, db_path):
        super().__init__()
        self.profiles_to_import = profiles_to_import
        self.db_path = db_path
        self._is_cancelled = False

    def run(self):
        """Run the import process."""
        # Create a new database connection for this thread
        # SQLite connections cannot be shared across threads
        db = Database(self.db_path)
        db.initialize_schema()
        import_service = ImportService(db)

        results = []

        for profile in self.profiles_to_import:
            if self._is_cancelled:
                break

            profile_name = profile.profile_name or profile.profile_id
            self.profile_started.emit(profile.browser_name, profile_name)

            try:
                result = import_service.import_profile(
                    profile,
                    progress_callback=self._on_progress
                )
                results.append(result)
                self.profile_finished.emit(result)
            except Exception as e:
                self.error_occurred.emit(f"Error importing {profile.browser_name}/{profile_name}: {e}")

        # Close the thread's database connection
        db.close()

        self.import_finished.emit(results)

    def _on_progress(self, progress: ImportProgress):
        """Handle progress updates from the import service."""
        if not self._is_cancelled:
            self.progress_updated.emit(progress)

    def cancel(self):
        """Cancel the import operation."""
        self._is_cancelled = True


class ImportDialog(QDialog):
    """Dialog for importing bookmarks with progress display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_detector = ProfileDetector()
        self.worker = None
        self.results = []

        # Get the database path for passing to worker thread
        from ..models.database import get_database
        self.db = get_database()
        self.db_path = self.db.db_path

        self.setup_ui()
        self.load_profiles()

    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Import Bookmarks")
        self.setMinimumSize(600, 500)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # Profile selection group
        profile_group = QGroupBox("Select Profiles to Import")
        profile_layout = QVBoxLayout(profile_group)

        # Select all checkbox
        self.select_all_checkbox = QCheckBox("Select All")
        self.select_all_checkbox.stateChanged.connect(self.on_select_all_changed)
        profile_layout.addWidget(self.select_all_checkbox)

        # Scrollable area for profile checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(150)

        self.profile_container = QWidget()
        self.profile_layout = QVBoxLayout(self.profile_container)
        self.profile_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_area.setWidget(self.profile_container)

        profile_layout.addWidget(scroll_area)
        layout.addWidget(profile_group)

        # Progress group
        progress_group = QGroupBox("Import Progress")
        progress_layout = QVBoxLayout(progress_group)

        # Current profile label
        self.current_profile_label = QLabel("Ready to import")
        progress_layout.addWidget(self.current_profile_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        # Current item label
        self.current_item_label = QLabel("")
        self.current_item_label.setStyleSheet("color: gray;")
        progress_layout.addWidget(self.current_item_label)

        layout.addWidget(progress_group)

        # Log/results area
        log_group = QGroupBox("Import Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.import_button = QPushButton("Start Import")
        self.import_button.clicked.connect(self.start_import)
        button_layout.addWidget(self.import_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setVisible(False)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def load_profiles(self):
        """Load available browser profiles."""
        self.profile_checkboxes = []
        profiles = self.profile_detector.detect_all_profiles()

        for profile in profiles:
            if profile.has_bookmarks_file:
                profile_name = profile.profile_name or profile.profile_id
                label = f"{profile.browser_name} - {profile_name} ({profile.bookmark_count} bookmarks)"

                checkbox = QCheckBox(label)
                checkbox.setChecked(True)
                checkbox.setProperty("profile", profile)
                self.profile_checkboxes.append(checkbox)
                self.profile_layout.addWidget(checkbox)

        # Update select all state
        self.select_all_checkbox.setChecked(True)

        if not self.profile_checkboxes:
            self.log_text.append("No browser profiles with bookmarks found.")
            self.import_button.setEnabled(False)

    def on_select_all_changed(self, state):
        """Handle select all checkbox change."""
        is_checked = state == Qt.CheckState.Checked.value
        for checkbox in self.profile_checkboxes:
            checkbox.setChecked(is_checked)

    def get_selected_profiles(self) -> list:
        """Get list of selected profiles."""
        selected = []
        for checkbox in self.profile_checkboxes:
            if checkbox.isChecked():
                profile = checkbox.property("profile")
                if profile:
                    selected.append(profile)
        return selected

    def start_import(self):
        """Start the import process."""
        selected_profiles = self.get_selected_profiles()

        if not selected_profiles:
            self.log_text.append("No profiles selected.")
            return

        # Disable UI during import
        self.import_button.setEnabled(False)
        self.select_all_checkbox.setEnabled(False)
        for checkbox in self.profile_checkboxes:
            checkbox.setEnabled(False)

        # Clear previous results
        self.results = []
        self.log_text.clear()
        self.log_text.append(f"Starting import of {len(selected_profiles)} profile(s)...\n")

        # Create and start worker thread
        self.worker = ImportWorker(selected_profiles, self.db_path)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.worker.profile_started.connect(self.on_profile_started)
        self.worker.profile_finished.connect(self.on_profile_finished)
        self.worker.import_finished.connect(self.on_import_finished)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def on_progress_updated(self, progress: ImportProgress):
        """Handle progress updates."""
        if progress.total_items > 0:
            percent = int((progress.current_item / progress.total_items) * 100)
            self.progress_bar.setValue(percent)

        # Truncate title for display
        title = progress.current_title
        if len(title) > 50:
            title = title[:47] + "..."

        self.current_item_label.setText(f"{progress.phase}: {title}")

    def on_profile_started(self, browser_name: str, profile_name: str):
        """Handle profile import start."""
        self.current_profile_label.setText(f"Importing: {browser_name} - {profile_name}")
        self.progress_bar.setValue(0)
        self.log_text.append(f"Importing {browser_name} - {profile_name}...")

    def on_profile_finished(self, result: ImportResult):
        """Handle profile import completion."""
        self.results.append(result)

        profile_name = result.profile.profile_display_name or result.profile.browser_profile_name
        self.log_text.append(
            f"  Completed: {result.bookmarks_added} added, "
            f"{result.bookmarks_skipped} skipped"
        )

        if result.errors:
            for error in result.errors:
                self.log_text.append(f"  Error: {error}")

    def on_import_finished(self, results: list):
        """Handle import completion."""
        self.worker = None
        self.progress_bar.setValue(100)
        self.current_profile_label.setText("Import complete!")
        self.current_item_label.setText("")

        # Calculate totals
        total_added = sum(r.bookmarks_added for r in results)
        total_skipped = sum(r.bookmarks_skipped for r in results)
        total_folders = sum(r.folders_added for r in results)

        self.log_text.append(f"\n{'='*40}")
        self.log_text.append(f"Import Summary:")
        self.log_text.append(f"  Profiles processed: {len(results)}")
        self.log_text.append(f"  Bookmarks added: {total_added}")
        self.log_text.append(f"  Bookmarks skipped: {total_skipped}")
        self.log_text.append(f"  Folders added: {total_folders}")

        # Show close button, hide cancel
        self.cancel_button.setVisible(False)
        self.close_button.setVisible(True)
        self.import_button.setVisible(False)

    def on_error(self, error_message: str):
        """Handle error during import."""
        self.log_text.append(f"ERROR: {error_message}")

    def on_cancel(self):
        """Handle cancel button click."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
            self.log_text.append("\nImport cancelled by user.")

        self.reject()

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        event.accept()
