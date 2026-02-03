"""Main application window for the Bookmark Manager."""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QLabel,
    QHeaderView,
    QStatusBar,
    QMessageBox,
    QMenu,
    QApplication,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QAction, QDesktopServices, QColor, QPixmap

from ..models.database import get_database, reset_database
from ..models.bookmark import Bookmark
from ..models.folder import Folder
from ..models.browser_profile import BrowserProfile
from .import_dialog import ImportDialog
from .dead_link_dialog import DeadLinkDialog
from .duplicate_dialog import DuplicateDialog, normalize_url
from .refresh_all_dialog import RefreshAllDialog
from .delete_bookmarks_dialog import DeleteBookmarksDialog
from .thumbnail_dialog import ThumbnailDialog
from ..services.thumbnail_service import get_thumbnail_service


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.db = get_database()
        self.current_folder_id = None
        self.current_profile_id = None
        self.all_bookmarks_mode = True

        # Caches for dead links and duplicates
        self.dead_link_bookmark_ids = set()
        self.exact_duplicate_counts = {}
        self.similar_duplicate_counts = {}

        # Thumbnail service
        self.thumbnail_service = get_thumbnail_service()
        self.thumbnail_service.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.thumbnail_service.thumbnail_error.connect(self.on_thumbnail_error)
        self.thumbnail_service.thumbnail_loading.connect(self.on_thumbnail_loading)

        # Currently selected bookmark URL for thumbnail
        self.selected_url = None

        self.setup_ui()
        self.load_status_data()
        self.load_data()

    def setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Bookmark Manager")
        self.setMinimumSize(1200, 600)

        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top bar with search and Refresh All button
        top_layout = QHBoxLayout()

        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search bookmarks by title, URL, or notes...")
        self.search_input.textChanged.connect(self.on_search_changed)
        top_layout.addWidget(search_label)
        top_layout.addWidget(self.search_input)

        top_layout.addSpacing(20)

        self.refresh_all_button = QPushButton("Refresh All...")
        self.refresh_all_button.clicked.connect(self.show_refresh_all_dialog)
        top_layout.addWidget(self.refresh_all_button)

        main_layout.addLayout(top_layout)

        # Create main splitter for sidebar, content, and preview
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left sidebar - folder tree
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folders")
        self.folder_tree.setMinimumWidth(200)
        self.folder_tree.itemClicked.connect(self.on_folder_clicked)
        main_splitter.addWidget(self.folder_tree)

        # Middle - bookmark table
        self.bookmark_table = QTableWidget()
        self.bookmark_table.setColumnCount(7)
        self.bookmark_table.setHorizontalHeaderLabels([
            "Title", "URL", "Folder", "Browser/Profile", "Dead", "Exact Dup", "Similar"
        ])

        # All columns interactive (resizable)
        for i in range(7):
            self.bookmark_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        # Set initial column widths
        self.bookmark_table.setColumnWidth(0, 250)  # Title
        self.bookmark_table.setColumnWidth(1, 350)  # URL
        self.bookmark_table.setColumnWidth(2, 120)  # Folder
        self.bookmark_table.setColumnWidth(3, 150)  # Browser/Profile
        self.bookmark_table.setColumnWidth(4, 50)   # Dead
        self.bookmark_table.setColumnWidth(5, 70)   # Exact Dup
        self.bookmark_table.setColumnWidth(6, 60)   # Similar

        self.bookmark_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bookmark_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bookmark_table.doubleClicked.connect(self.on_bookmark_double_clicked)
        self.bookmark_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bookmark_table.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        self.bookmark_table.itemSelectionChanged.connect(self.on_bookmark_selection_changed)
        main_splitter.addWidget(self.bookmark_table)

        # Right sidebar - thumbnail preview
        self.preview_panel = self._create_preview_panel()
        main_splitter.addWidget(self.preview_panel)

        # Set splitter sizes (20% folder tree, 55% content, 25% preview)
        main_splitter.setSizes([200, 650, 350])
        main_layout.addWidget(main_splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create menu bar
        self.create_menu_bar()

    def _create_preview_panel(self) -> QWidget:
        """Create the thumbnail preview panel."""
        panel = QWidget()
        panel.setMinimumWidth(250)
        panel.setMaximumWidth(500)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)

        # Title
        title_label = QLabel("<b>Page Preview</b>")
        layout.addWidget(title_label)

        # Bookmark info section
        info_frame = QFrame()
        info_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 5px;")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(4)

        self.preview_title_label = QLabel("Select a bookmark to preview")
        self.preview_title_label.setWordWrap(True)
        self.preview_title_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.preview_title_label)

        self.preview_url_label = QLabel("")
        self.preview_url_label.setWordWrap(True)
        self.preview_url_label.setStyleSheet("color: #0066cc; font-size: 11px;")
        self.preview_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.preview_url_label)

        self.preview_folder_label = QLabel("")
        self.preview_folder_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.preview_folder_label)

        layout.addWidget(info_frame)

        # Thumbnail image
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setMinimumHeight(200)
        self.thumbnail_label.setStyleSheet(
            "background-color: #e9ecef; border: 1px solid #dee2e6; border-radius: 4px;"
        )
        self.thumbnail_label.setText("No preview available")

        # Make thumbnail clickable to open URL
        self.thumbnail_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumbnail_label.mousePressEvent = self._on_thumbnail_clicked

        layout.addWidget(self.thumbnail_label, 1)  # Give it stretch

        # Buttons
        button_layout = QHBoxLayout()

        self.open_url_btn = QPushButton("Open in Browser")
        self.open_url_btn.clicked.connect(self._open_selected_url)
        self.open_url_btn.setEnabled(False)
        button_layout.addWidget(self.open_url_btn)

        self.refresh_thumb_btn = QPushButton("Refresh")
        self.refresh_thumb_btn.setToolTip("Regenerate thumbnail")
        self.refresh_thumb_btn.clicked.connect(self._refresh_thumbnail)
        self.refresh_thumb_btn.setEnabled(False)
        button_layout.addWidget(self.refresh_thumb_btn)

        layout.addLayout(button_layout)

        # Status
        self.preview_status_label = QLabel("")
        self.preview_status_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.preview_status_label)

        return panel

    def on_bookmark_selection_changed(self):
        """Handle bookmark selection change - update preview panel."""
        selected_rows = self.bookmark_table.selectionModel().selectedRows()
        if not selected_rows:
            self._clear_preview()
            return

        row = selected_rows[0].row()
        title_item = self.bookmark_table.item(row, 0)
        url_item = self.bookmark_table.item(row, 1)
        folder_item = self.bookmark_table.item(row, 2)

        if not url_item:
            self._clear_preview()
            return

        url = url_item.text()
        title = title_item.text() if title_item else "(no title)"
        folder = folder_item.text() if folder_item else ""

        self.selected_url = url

        # Update info labels
        self.preview_title_label.setText(title)
        self.preview_url_label.setText(url[:100] + "..." if len(url) > 100 else url)
        self.preview_url_label.setToolTip(url)
        self.preview_folder_label.setText(f"📁 {folder}" if folder else "")

        # Enable buttons
        self.open_url_btn.setEnabled(True)
        self.refresh_thumb_btn.setEnabled(True)

        # Try to get thumbnail
        self._load_thumbnail(url)

    def _clear_preview(self):
        """Clear the preview panel."""
        self.selected_url = None
        self.preview_title_label.setText("Select a bookmark to preview")
        self.preview_url_label.setText("")
        self.preview_folder_label.setText("")
        self.thumbnail_label.setPixmap(QPixmap())
        self.thumbnail_label.setText("No preview available")
        self.preview_status_label.setText("")
        self.open_url_btn.setEnabled(False)
        self.refresh_thumb_btn.setEnabled(False)

    def _load_thumbnail(self, url: str):
        """Load thumbnail for URL."""
        pixmap = self.thumbnail_service.get_thumbnail(url)
        if pixmap:
            self._display_thumbnail(pixmap)
            self.preview_status_label.setText("From cache")
        else:
            self.thumbnail_label.setText("Loading preview...")
            self.preview_status_label.setText("Generating thumbnail...")

    def _display_thumbnail(self, pixmap: QPixmap):
        """Display a thumbnail in the preview panel."""
        if pixmap.isNull():
            self.thumbnail_label.setText("Preview not available")
            return

        # Scale to fit the label while maintaining aspect ratio
        label_size = self.thumbnail_label.size()
        scaled = pixmap.scaled(
            label_size.width() - 10,
            label_size.height() - 10,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.thumbnail_label.setPixmap(scaled)

    def on_thumbnail_ready(self, url: str, pixmap: QPixmap):
        """Handle thumbnail generation complete."""
        if url == self.selected_url:
            self._display_thumbnail(pixmap)
            self.preview_status_label.setText("Thumbnail generated")

    def on_thumbnail_error(self, url: str, error: str):
        """Handle thumbnail generation error."""
        if url == self.selected_url:
            self.thumbnail_label.setText(f"Preview error:\n{error[:50]}")
            self.preview_status_label.setText(f"Error: {error[:30]}")

    def on_thumbnail_loading(self, url: str):
        """Handle thumbnail loading started."""
        if url == self.selected_url:
            self.thumbnail_label.setText("Loading preview...")
            self.preview_status_label.setText("Generating...")

    def _on_thumbnail_clicked(self, event):
        """Handle click on thumbnail - open URL."""
        if self.selected_url:
            QDesktopServices.openUrl(QUrl(self.selected_url))

    def _open_selected_url(self):
        """Open the selected URL in browser."""
        if self.selected_url:
            QDesktopServices.openUrl(QUrl(self.selected_url))

    def _refresh_thumbnail(self):
        """Refresh the thumbnail for the selected URL."""
        if self.selected_url:
            self.thumbnail_label.setText("Refreshing preview...")
            self.preview_status_label.setText("Regenerating...")
            self.thumbnail_service.get_thumbnail(self.selected_url, force_refresh=True)

    def create_menu_bar(self):
        """Create the menu bar."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        refresh_all_action = QAction("Refresh &All...", self)
        refresh_all_action.setShortcut("Ctrl+Shift+R")
        refresh_all_action.triggered.connect(self.show_refresh_all_dialog)
        file_menu.addAction(refresh_all_action)

        file_menu.addSeparator()

        import_action = QAction("&Import from Browsers...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.show_import_dialog)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        duplicate_action = QAction("Find D&uplicates...", self)
        duplicate_action.setShortcut("Ctrl+U")
        duplicate_action.triggered.connect(self.show_duplicate_dialog)
        file_menu.addAction(duplicate_action)

        dead_link_action = QAction("Check &Dead Links...", self)
        dead_link_action.setShortcut("Ctrl+D")
        dead_link_action.triggered.connect(self.show_dead_link_dialog)
        file_menu.addAction(dead_link_action)

        thumbnail_action = QAction("Generate &Thumbnails...", self)
        thumbnail_action.setShortcut("Ctrl+T")
        thumbnail_action.triggered.connect(self.show_thumbnail_dialog)
        file_menu.addAction(thumbnail_action)

        file_menu.addSeparator()

        delete_bookmarks_action = QAction("Delete from &Browsers...", self)
        delete_bookmarks_action.setShortcut("Ctrl+Shift+D")
        delete_bookmarks_action.triggered.connect(self.show_delete_bookmarks_dialog)
        file_menu.addAction(delete_bookmarks_action)

        file_menu.addSeparator()

        refresh_action = QAction("&Refresh View", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_view)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")

        show_all_action = QAction("Show &All Bookmarks", self)
        show_all_action.setShortcut("Ctrl+A")
        show_all_action.triggered.connect(self.show_all_bookmarks)
        view_menu.addAction(show_all_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def load_status_data(self):
        """Load dead link and duplicate status data from database."""
        # Load dead link bookmark IDs (from most recent check)
        self.dead_link_bookmark_ids = set()
        try:
            cursor = self.db.execute("""
                SELECT DISTINCT bookmark_id FROM dead_links
                WHERE check_run_id = (
                    SELECT check_run_id FROM dead_links
                    ORDER BY checked_at DESC LIMIT 1
                )
            """)
            for row in cursor.fetchall():
                self.dead_link_bookmark_ids.add(row['bookmark_id'])
        except Exception:
            pass

        # Load exact duplicate counts (from most recent check)
        self.exact_duplicate_counts = {}
        try:
            cursor = self.db.execute("""
                SELECT dgm.bookmark_id,
                       (SELECT COUNT(*) FROM duplicate_group_members dgm2
                        WHERE dgm2.duplicate_group_id = dgm.duplicate_group_id) as group_size
                FROM duplicate_group_members dgm
                JOIN duplicate_groups dg ON dgm.duplicate_group_id = dg.duplicate_group_id
                WHERE dg.match_type = 'exact'
                AND dg.check_run_id = (
                    SELECT check_run_id FROM duplicate_groups
                    WHERE match_type = 'exact'
                    ORDER BY created_at DESC LIMIT 1
                )
            """)
            for row in cursor.fetchall():
                self.exact_duplicate_counts[row['bookmark_id']] = row['group_size']
        except Exception:
            pass

        # Load similar duplicate counts (from most recent check)
        self.similar_duplicate_counts = {}
        try:
            cursor = self.db.execute("""
                SELECT dgm.bookmark_id,
                       (SELECT COUNT(*) FROM duplicate_group_members dgm2
                        WHERE dgm2.duplicate_group_id = dgm.duplicate_group_id) as group_size
                FROM duplicate_group_members dgm
                JOIN duplicate_groups dg ON dgm.duplicate_group_id = dg.duplicate_group_id
                WHERE dg.match_type = 'similar'
                AND dg.check_run_id = (
                    SELECT check_run_id FROM duplicate_groups
                    WHERE match_type = 'similar'
                    ORDER BY created_at DESC LIMIT 1
                )
            """)
            for row in cursor.fetchall():
                self.similar_duplicate_counts[row['bookmark_id']] = row['group_size']
        except Exception:
            pass

    def refresh_view(self):
        """Refresh the view with latest data."""
        self.load_status_data()
        self.load_data()

    def load_data(self):
        """Load all data from database."""
        self.load_folder_tree()
        self.load_bookmarks()
        self.update_status_bar()

    def load_folder_tree(self):
        """Load the folder tree in the sidebar."""
        self.folder_tree.clear()

        # Add "All Bookmarks" item at top
        all_item = QTreeWidgetItem(["All Bookmarks"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "all"})
        self.folder_tree.addTopLevelItem(all_item)

        # Get all profiles
        profiles = BrowserProfile.get_all(self.db)

        for profile in profiles:
            # Create profile node
            profile_name = profile.profile_display_name or profile.browser_profile_name
            profile_item = QTreeWidgetItem([f"{profile.browser_name} - {profile_name}"])
            profile_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "profile",
                "profile_id": profile.browser_profile_id
            })
            self.folder_tree.addTopLevelItem(profile_item)

            # Get folders for this profile
            folders = Folder.get_by_profile(self.db, profile.browser_profile_id)

            # Build folder hierarchy
            folder_items = {}
            root_folders = []

            # First pass - create all folder items
            for folder in folders:
                folder_item = QTreeWidgetItem([folder.name])
                folder_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "folder",
                    "folder_id": folder.folder_id,
                    "profile_id": profile.browser_profile_id
                })
                folder_items[folder.folder_id] = (folder, folder_item)

                if folder.parent_folder_id is None:
                    root_folders.append(folder.folder_id)

            # Second pass - build hierarchy
            for folder_id, (folder, folder_item) in folder_items.items():
                if folder.parent_folder_id is None:
                    profile_item.addChild(folder_item)
                elif folder.parent_folder_id in folder_items:
                    parent_item = folder_items[folder.parent_folder_id][1]
                    parent_item.addChild(folder_item)

        # Expand the "All Bookmarks" item
        all_item.setExpanded(True)

    def load_bookmarks(self, folder_id=None, profile_id=None, search_query=None):
        """Load bookmarks into the table.

        Args:
            folder_id: Filter by folder ID, or None for all
            profile_id: Filter by profile ID, or None for all
            search_query: Search query string, or None for no search
        """
        self.bookmark_table.setRowCount(0)

        if search_query:
            # Use full-text search
            bookmarks = Bookmark.search(self.db, search_query)
        elif folder_id is not None:
            bookmarks = Bookmark.get_by_folder(self.db, folder_id)
        elif profile_id is not None:
            bookmarks = Bookmark.get_by_profile(self.db, profile_id)
        else:
            bookmarks = Bookmark.get_all(self.db)

        # Get folder and profile info for display
        folder_cache = {}
        profile_cache = {}

        for bookmark in bookmarks:
            row = self.bookmark_table.rowCount()
            self.bookmark_table.insertRow(row)

            # Title
            title_item = QTableWidgetItem(bookmark.title or "(no title)")
            title_item.setData(Qt.ItemDataRole.UserRole, bookmark.bookmark_id)
            self.bookmark_table.setItem(row, 0, title_item)

            # URL
            url_item = QTableWidgetItem(bookmark.url)
            self.bookmark_table.setItem(row, 1, url_item)

            # Folder name
            folder_name = ""
            if bookmark.folder_id:
                if bookmark.folder_id not in folder_cache:
                    folder = Folder.find_by_id(self.db, bookmark.folder_id)
                    folder_cache[bookmark.folder_id] = folder.name if folder else ""
                folder_name = folder_cache[bookmark.folder_id]
            folder_item = QTableWidgetItem(folder_name)
            self.bookmark_table.setItem(row, 2, folder_item)

            # Browser/Profile
            profile_str = ""
            if bookmark.browser_profile_id:
                if bookmark.browser_profile_id not in profile_cache:
                    profile = BrowserProfile.find_by_id(self.db, bookmark.browser_profile_id)
                    if profile:
                        profile_cache[bookmark.browser_profile_id] = (
                            f"{profile.browser_name}/{profile.profile_display_name or profile.browser_profile_name}"
                        )
                    else:
                        profile_cache[bookmark.browser_profile_id] = ""
                profile_str = profile_cache[bookmark.browser_profile_id]
            profile_item = QTableWidgetItem(profile_str)
            self.bookmark_table.setItem(row, 3, profile_item)

            # Dead link flag
            dead_item = QTableWidgetItem()
            if bookmark.bookmark_id in self.dead_link_bookmark_ids:
                dead_item.setText("X")
                dead_item.setForeground(QColor(255, 0, 0))  # Red
            self.bookmark_table.setItem(row, 4, dead_item)

            # Exact duplicate count
            exact_dup_item = QTableWidgetItem()
            if bookmark.bookmark_id in self.exact_duplicate_counts:
                count = self.exact_duplicate_counts[bookmark.bookmark_id]
                if count > 1:
                    exact_dup_item.setText(str(count))
                    exact_dup_item.setForeground(QColor(255, 140, 0))  # Orange
            self.bookmark_table.setItem(row, 5, exact_dup_item)

            # Similar duplicate count
            similar_dup_item = QTableWidgetItem()
            if bookmark.bookmark_id in self.similar_duplicate_counts:
                count = self.similar_duplicate_counts[bookmark.bookmark_id]
                if count > 1:
                    similar_dup_item.setText(str(count))
                    similar_dup_item.setForeground(QColor(0, 100, 200))  # Blue
            self.bookmark_table.setItem(row, 6, similar_dup_item)

        self.update_status_bar()

    def on_folder_clicked(self, item, column):
        """Handle folder tree item click."""
        data = item.data(0, Qt.ItemDataRole.UserRole)

        if data is None:
            return

        item_type = data.get("type")

        if item_type == "all":
            self.all_bookmarks_mode = True
            self.current_folder_id = None
            self.current_profile_id = None
            self.load_bookmarks()
        elif item_type == "profile":
            self.all_bookmarks_mode = False
            self.current_folder_id = None
            self.current_profile_id = data.get("profile_id")
            self.load_bookmarks(profile_id=self.current_profile_id)
        elif item_type == "folder":
            self.all_bookmarks_mode = False
            self.current_folder_id = data.get("folder_id")
            self.current_profile_id = data.get("profile_id")
            self.load_bookmarks(folder_id=self.current_folder_id)

    def on_search_changed(self, text):
        """Handle search input change."""
        if text.strip():
            self.load_bookmarks(search_query=text.strip())
        else:
            # Restore previous view
            if self.all_bookmarks_mode:
                self.load_bookmarks()
            elif self.current_folder_id:
                self.load_bookmarks(folder_id=self.current_folder_id)
            elif self.current_profile_id:
                self.load_bookmarks(profile_id=self.current_profile_id)
            else:
                self.load_bookmarks()

    def on_bookmark_double_clicked(self, index):
        """Handle bookmark double-click - open URL in browser."""
        row = index.row()
        url_item = self.bookmark_table.item(row, 1)
        if url_item:
            url = url_item.text()
            QDesktopServices.openUrl(QUrl(url))

    def show_bookmark_context_menu(self, position):
        """Show context menu for bookmark table."""
        item = self.bookmark_table.itemAt(position)
        if item is None:
            return

        row = item.row()
        url_item = self.bookmark_table.item(row, 1)
        title_item = self.bookmark_table.item(row, 0)

        if url_item is None:
            return

        menu = QMenu(self)

        # Open in browser
        open_action = QAction("Open in Browser", self)
        open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(url_item.text())))
        menu.addAction(open_action)

        menu.addSeparator()

        # Generate/refresh thumbnail
        url = url_item.text()
        thumb_action = QAction("Generate Thumbnail", self)
        thumb_action.triggered.connect(lambda: self._generate_thumbnail_for_url(url))
        menu.addAction(thumb_action)

        menu.addSeparator()

        # Copy URL
        copy_url_action = QAction("Copy URL", self)
        copy_url_action.triggered.connect(lambda: QApplication.clipboard().setText(url_item.text()))
        menu.addAction(copy_url_action)

        # Copy title
        if title_item:
            copy_title_action = QAction("Copy Title", self)
            copy_title_action.triggered.connect(lambda: QApplication.clipboard().setText(title_item.text()))
            menu.addAction(copy_title_action)

        menu.exec(self.bookmark_table.mapToGlobal(position))

    def _generate_thumbnail_for_url(self, url: str):
        """Generate thumbnail for a specific URL."""
        self.thumbnail_service.get_thumbnail(url, force_refresh=True)
        if url == self.selected_url:
            self.thumbnail_label.setText("Generating preview...")
            self.preview_status_label.setText("Generating...")

    def show_all_bookmarks(self):
        """Show all bookmarks."""
        self.all_bookmarks_mode = True
        self.current_folder_id = None
        self.current_profile_id = None
        self.search_input.clear()
        self.load_bookmarks()

    def update_status_bar(self):
        """Update the status bar with current stats."""
        total = Bookmark.count(self.db)
        shown = self.bookmark_table.rowCount()
        dead_count = len(self.dead_link_bookmark_ids)
        dup_count = len([c for c in self.exact_duplicate_counts.values() if c > 1])

        if shown == total:
            msg = f"Showing all {total} bookmarks"
        else:
            msg = f"Showing {shown} of {total} bookmarks"

        if dead_count > 0:
            msg += f" | {dead_count} dead links"
        if dup_count > 0:
            msg += f" | {dup_count} with duplicates"

        self.status_bar.showMessage(msg)

    def show_import_dialog(self):
        """Show the import dialog."""
        dialog = ImportDialog(self)
        dialog.exec()
        # Refresh data after import
        self.load_data()

    def show_dead_link_dialog(self):
        """Show the dead link checker dialog."""
        dialog = DeadLinkDialog(self)
        dialog.exec()
        # Refresh status data after check
        self.load_status_data()
        self.load_bookmarks()

    def show_duplicate_dialog(self):
        """Show the duplicate finder dialog."""
        dialog = DuplicateDialog(self)
        dialog.exec()
        # Refresh status data after check
        self.load_status_data()
        self.load_bookmarks()

    def show_refresh_all_dialog(self):
        """Show the refresh all dialog."""
        dialog = RefreshAllDialog(self)
        dialog.database_reset.connect(self.on_database_reset)
        dialog.exec()
        # Refresh everything after
        self.load_status_data()
        self.load_data()

    def show_delete_bookmarks_dialog(self):
        """Show the delete bookmarks dialog."""
        dialog = DeleteBookmarksDialog(self)
        dialog.exec()
        # Refresh everything after (bookmarks may have been deleted)
        self.load_status_data()
        self.load_data()

    def show_thumbnail_dialog(self):
        """Show the thumbnail generation dialog."""
        # Get selected URLs if any rows are selected
        selected_urls = None
        selected_rows = self.bookmark_table.selectionModel().selectedRows()
        if selected_rows:
            selected_urls = []
            for row_idx in selected_rows:
                url_item = self.bookmark_table.item(row_idx.row(), 1)
                if url_item:
                    selected_urls.append(url_item.text())

        dialog = ThumbnailDialog(selected_urls, self)
        dialog.exec()

    def on_database_reset(self):
        """Handle database reset - get new connection."""
        # Reset and get fresh database connection
        reset_database()
        self.db = get_database()

    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Bookmark Manager",
            "Bookmark Manager v0.1\n\n"
            "A desktop application to organize and manage bookmarks\n"
            "imported from Chrome and Edge browsers.\n\n"
            "Features:\n"
            "- Import bookmarks from multiple browser profiles\n"
            "- Full-text search\n"
            "- Folder navigation\n"
            "- Dead link detection\n"
            "- Duplicate detection\n"
            "- Open bookmarks in your default browser"
        )
