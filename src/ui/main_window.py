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
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices

from ..models.database import get_database
from ..models.bookmark import Bookmark
from ..models.folder import Folder
from ..models.browser_profile import BrowserProfile
from .import_dialog import ImportDialog
from .dead_link_dialog import DeadLinkDialog
from .duplicate_dialog import DuplicateDialog


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.db = get_database()
        self.current_folder_id = None
        self.current_profile_id = None
        self.all_bookmarks_mode = True

        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Bookmark Manager")
        self.setMinimumSize(1000, 600)

        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Search bar at the top
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search bookmarks by title, URL, or notes...")
        self.search_input.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        main_layout.addLayout(search_layout)

        # Create splitter for sidebar and main content
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left sidebar - folder tree
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folders")
        self.folder_tree.setMinimumWidth(250)
        self.folder_tree.itemClicked.connect(self.on_folder_clicked)
        splitter.addWidget(self.folder_tree)

        # Right side - bookmark table
        self.bookmark_table = QTableWidget()
        self.bookmark_table.setColumnCount(4)
        self.bookmark_table.setHorizontalHeaderLabels(["Title", "URL", "Folder", "Browser/Profile"])
        self.bookmark_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.bookmark_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bookmark_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.bookmark_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.bookmark_table.setColumnWidth(0, 250)
        self.bookmark_table.setColumnWidth(2, 150)
        self.bookmark_table.setColumnWidth(3, 150)
        self.bookmark_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bookmark_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bookmark_table.doubleClicked.connect(self.on_bookmark_double_clicked)
        self.bookmark_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bookmark_table.customContextMenuRequested.connect(self.show_bookmark_context_menu)
        splitter.addWidget(self.bookmark_table)

        # Set splitter sizes (30% sidebar, 70% content)
        splitter.setSizes([300, 700])
        main_layout.addWidget(splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Create menu bar
        self.create_menu_bar()

    def create_menu_bar(self):
        """Create the menu bar."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")

        import_action = QAction("&Import from Browsers...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.show_import_dialog)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        dead_link_action = QAction("Check &Dead Links...", self)
        dead_link_action.setShortcut("Ctrl+D")
        dead_link_action.triggered.connect(self.show_dead_link_dialog)
        file_menu.addAction(dead_link_action)

        duplicate_action = QAction("Find D&uplicates...", self)
        duplicate_action.setShortcut("Ctrl+U")
        duplicate_action.triggered.connect(self.show_duplicate_dialog)
        file_menu.addAction(duplicate_action)

        file_menu.addSeparator()

        refresh_action = QAction("&Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.load_data)
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

        if shown == total:
            self.status_bar.showMessage(f"Showing all {total} bookmarks")
        else:
            self.status_bar.showMessage(f"Showing {shown} of {total} bookmarks")

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

    def show_duplicate_dialog(self):
        """Show the duplicate finder dialog."""
        dialog = DuplicateDialog(self)
        dialog.exec()

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
            "- Open bookmarks in your default browser"
        )
