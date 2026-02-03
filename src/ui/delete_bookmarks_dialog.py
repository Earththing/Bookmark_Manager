"""Dialog for selecting and deleting bookmarks from browsers."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSortFilterProxyModel
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QGroupBox,
    QMessageBox, QProgressDialog, QCheckBox, QHeaderView, QFrame,
    QSplitter, QTextEdit, QComboBox, QRadioButton, QButtonGroup, QMenu,
    QLineEdit, QToolButton, QWidgetAction, QListWidget, QListWidgetItem,
    QAbstractItemView, QApplication, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem
)
from PyQt6.QtGui import QColor, QBrush, QFont, QAction
from PyQt6.QtCore import QTimer

from ..models.database import get_database, Database
from ..models.bookmark import Bookmark
from ..services.bookmark_modifier import BookmarkModifierService, BookmarkToDelete
from ..services.browser_process import BrowserProcessService
from ..services.import_service import ImportService


def parse_url_components(url: str) -> Tuple[str, str, str]:
    """Parse a URL into its domain components.

    Args:
        url: The URL to parse

    Returns:
        Tuple of (subdomain, domain, tld)
        - subdomain: e.g., "www" or "blog" or "" if none
        - domain: e.g., "example" (second-level domain)
        - tld: e.g., "com" or "co.uk" (top-level domain)
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()

        # Remove port if present
        if ':' in hostname:
            hostname = hostname.split(':')[0]

        if not hostname:
            return ("", "", "")

        # Handle IP addresses
        if hostname.replace('.', '').isdigit():
            return ("", hostname, "")

        parts = hostname.split('.')

        # Common multi-part TLDs
        multi_tlds = {'co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.in',
                      'org.uk', 'net.au', 'gov.uk', 'ac.uk', 'edu.au'}

        if len(parts) >= 2:
            # Check for multi-part TLD
            potential_multi_tld = '.'.join(parts[-2:])
            if potential_multi_tld in multi_tlds:
                tld = potential_multi_tld
                if len(parts) >= 3:
                    domain = parts[-3]
                    subdomain = '.'.join(parts[:-3]) if len(parts) > 3 else ""
                else:
                    domain = ""
                    subdomain = ""
            else:
                tld = parts[-1]
                domain = parts[-2] if len(parts) >= 2 else ""
                subdomain = '.'.join(parts[:-2]) if len(parts) > 2 else ""
        elif len(parts) == 1:
            return ("", parts[0], "")
        else:
            return ("", "", "")

        return (subdomain, domain, tld)

    except Exception:
        return ("", "", "")


class FilterListWidget(QWidget):
    """A compact filter widget with a searchable checkbox list."""

    filterChanged = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.all_values: List[str] = []
        self.checkboxes: Dict[str, QCheckBox] = {}

        self.setup_ui()

    def setup_ui(self):
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Header with title and buttons
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>{self.title}</b>"))
        header.addStretch()

        all_btn = QPushButton("All")
        all_btn.setFixedSize(35, 22)
        all_btn.setToolTip("Select all")
        all_btn.clicked.connect(self.select_all)
        header.addWidget(all_btn)

        none_btn = QPushButton("None")
        none_btn.setFixedSize(40, 22)
        none_btn.setToolTip("Clear selection")
        none_btn.clicked.connect(self.clear_selection)
        header.addWidget(none_btn)

        layout.addLayout(header)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter...")
        self.search_box.setMaximumHeight(24)
        self.search_box.textChanged.connect(self._filter_list)
        layout.addWidget(self.search_box)

        # Scrollable list of checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(80)
        scroll.setMaximumHeight(150)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(1)
        self.list_layout.addStretch()

        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

        # Status
        self.status_label = QLabel("No filter")
        self.status_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.status_label)

    def set_values(self, values: List[str]):
        """Set available values."""
        # Remember checked values
        checked = {v for v, cb in self.checkboxes.items() if cb.isChecked()}

        # Clear old checkboxes
        for cb in self.checkboxes.values():
            cb.deleteLater()
        self.checkboxes.clear()

        # Remove stretch item
        while self.list_layout.count() > 0:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.all_values = sorted(set(v for v in values if v))

        # Create checkboxes
        for value in self.all_values:
            cb = QCheckBox(value[:40] + "..." if len(value) > 40 else value)
            cb.setToolTip(value)
            cb.setChecked(value in checked)
            cb.stateChanged.connect(self._on_changed)
            self.checkboxes[value] = cb
            self.list_layout.addWidget(cb)

        self.list_layout.addStretch()
        self._update_status()

    def _filter_list(self, text: str):
        """Filter visible checkboxes."""
        text = text.lower()
        for value, cb in self.checkboxes.items():
            cb.setVisible(text in value.lower() if text else True)

    def _on_changed(self, state):
        """Handle checkbox change."""
        self._update_status()
        self.filterChanged.emit()

    def _update_status(self):
        """Update status label."""
        checked = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        total = len(self.checkboxes)
        if checked == 0:
            self.status_label.setText("No filter (showing all)")
        else:
            self.status_label.setText(f"{checked} of {total} selected")

    def get_selected(self) -> Optional[Set[str]]:
        """Get selected values, or None if no filter."""
        selected = {v for v, cb in self.checkboxes.items() if cb.isChecked()}
        return selected if selected else None

    def select_all(self):
        """Select all visible checkboxes."""
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
        self._update_status()
        self.filterChanged.emit()

    def clear_selection(self):
        """Clear all selections."""
        for cb in self.checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.search_box.clear()
        self._update_status()
        self.filterChanged.emit()


@dataclass
class DeletionItem:
    """An item that can be selected for deletion."""
    bookmark_id: int
    browser_bookmark_id: str
    browser_name: str
    profile_path: str
    profile_name: str
    url: str
    title: str
    reason: str  # "dead_link", "exact_duplicate", "similar_duplicate"
    group_id: Optional[int] = None  # For duplicates, which group they belong to
    folder_path: Optional[str] = None  # Folder location in browser bookmarks
    dead_link_detail: Optional[str] = None  # Status code or error message for dead links
    # URL components for filtering
    url_subdomain: str = ""
    url_domain: str = ""
    url_tld: str = ""

    def __post_init__(self):
        """Parse URL components after initialization."""
        if self.url and not self.url_domain:
            self.url_subdomain, self.url_domain, self.url_tld = parse_url_components(self.url)


class DeleteBookmarksDialog(QDialog):
    """Dialog for selecting bookmarks to delete from browsers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_database()
        self.modifier_service = BookmarkModifierService()

        # All items that could be deleted, keyed by bookmark_id
        self.all_items: Dict[int, DeletionItem] = {}

        # Selected for deletion (bookmark_id -> True)
        self.selected_for_deletion: Set[int] = set()

        # For duplicates: which bookmark to KEEP in each group (group_id -> bookmark_id)
        self.keep_in_group: Dict[int, int] = {}

        # Filter widgets
        self.filter_widgets: Dict[str, FilterListWidget] = {}

        # Track visible items
        self.visible_items: Set[int] = set()

        self.setWindowTitle("Delete Bookmarks from Browsers")
        self.setMinimumSize(1500, 900)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Warning banner - compact
        warning_frame = QFrame()
        warning_frame.setStyleSheet(
            "background-color: #fff3cd; border: 1px solid #ffc107; "
            "border-radius: 4px; padding: 6px;"
        )
        warning_frame.setFixedHeight(40)
        warning_layout = QHBoxLayout(warning_frame)
        warning_layout.setContentsMargins(10, 0, 10, 0)
        warning_label = QLabel(
            "⚠️ <b>Warning:</b> This will permanently delete selected bookmarks. "
            "Backups are created automatically."
        )
        warning_layout.addWidget(warning_label)
        layout.addWidget(warning_frame)

        # Main content - horizontal splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANEL - Filters (in a tab widget for organization)
        filter_panel = QWidget()
        filter_panel.setMinimumWidth(280)
        filter_panel.setMaximumWidth(400)
        filter_layout = QVBoxLayout(filter_panel)
        filter_layout.setContentsMargins(0, 0, 0, 0)

        # Filter tabs
        filter_tabs = QTabWidget()
        filter_tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; }")

        # Tab 1: Categories & Source
        cat_tab = QWidget()
        cat_layout = QVBoxLayout(cat_tab)
        cat_layout.setContentsMargins(8, 8, 8, 8)

        # Category checkboxes
        cat_group = QGroupBox("Categories")
        cat_group_layout = QVBoxLayout(cat_group)

        self.dead_links_check = QCheckBox("Dead Links")
        self.dead_links_check.setChecked(True)
        self.dead_links_check.stateChanged.connect(self.apply_filters)
        cat_group_layout.addWidget(self.dead_links_check)

        self.exact_dups_check = QCheckBox("Exact Duplicates")
        self.exact_dups_check.setChecked(True)
        self.exact_dups_check.stateChanged.connect(self.apply_filters)
        cat_group_layout.addWidget(self.exact_dups_check)

        self.similar_dups_check = QCheckBox("Similar Duplicates")
        self.similar_dups_check.setChecked(True)
        self.similar_dups_check.stateChanged.connect(self.apply_filters)
        cat_group_layout.addWidget(self.similar_dups_check)

        cat_layout.addWidget(cat_group)

        # Browser filter
        self.browser_filter = FilterListWidget("Browser")
        self.browser_filter.filterChanged.connect(self.apply_filters)
        cat_layout.addWidget(self.browser_filter)

        # Profile filter
        self.profile_filter = FilterListWidget("Profile")
        self.profile_filter.filterChanged.connect(self.apply_filters)
        cat_layout.addWidget(self.profile_filter)

        cat_layout.addStretch()
        filter_tabs.addTab(cat_tab, "Source")

        # Tab 2: URL Filters
        url_tab = QWidget()
        url_layout = QVBoxLayout(url_tab)
        url_layout.setContentsMargins(8, 8, 8, 8)

        # Domain filter
        self.domain_filter = FilterListWidget("Domain")
        self.domain_filter.filterChanged.connect(self.apply_filters)
        url_layout.addWidget(self.domain_filter)

        # TLD filter
        self.tld_filter = FilterListWidget("TLD")
        self.tld_filter.filterChanged.connect(self.apply_filters)
        url_layout.addWidget(self.tld_filter)

        # Subdomain filter
        self.subdomain_filter = FilterListWidget("Subdomain")
        self.subdomain_filter.filterChanged.connect(self.apply_filters)
        url_layout.addWidget(self.subdomain_filter)

        url_layout.addStretch()
        filter_tabs.addTab(url_tab, "URL")

        # Tab 3: Status Filters
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)
        status_layout.setContentsMargins(8, 8, 8, 8)

        # Dead link error filter
        self.dead_link_filter = FilterListWidget("Dead Link Error")
        self.dead_link_filter.filterChanged.connect(self.apply_filters)
        status_layout.addWidget(self.dead_link_filter)

        # Duplicate type filter
        self.duplicate_filter = FilterListWidget("Duplicate Type")
        self.duplicate_filter.filterChanged.connect(self.apply_filters)
        status_layout.addWidget(self.duplicate_filter)

        # Folder filter
        self.folder_filter = FilterListWidget("Folder")
        self.folder_filter.filterChanged.connect(self.apply_filters)
        status_layout.addWidget(self.folder_filter)

        status_layout.addStretch()
        filter_tabs.addTab(status_tab, "Status")

        filter_layout.addWidget(filter_tabs)

        # Quick Actions
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions_group)

        select_all_btn = QPushButton("Select All Visible")
        select_all_btn.clicked.connect(self.select_all_visible)
        actions_layout.addWidget(select_all_btn)

        deselect_btn = QPushButton("Deselect All")
        deselect_btn.clicked.connect(self.deselect_all)
        actions_layout.addWidget(deselect_btn)

        auto_select_btn = QPushButton("Auto-Select Duplicates")
        auto_select_btn.setToolTip("Keep first in each group, select rest")
        auto_select_btn.clicked.connect(self.auto_select_duplicates)
        actions_layout.addWidget(auto_select_btn)

        clear_filters_btn = QPushButton("Clear All Filters")
        clear_filters_btn.clicked.connect(self.clear_all_filters)
        actions_layout.addWidget(clear_filters_btn)

        # Generate thumbnails for filtered items
        thumb_btn = QPushButton("Generate Thumbnails...")
        thumb_btn.setToolTip("Generate thumbnails for currently visible items")
        thumb_btn.clicked.connect(self.generate_thumbnails_for_visible)
        actions_layout.addWidget(thumb_btn)

        filter_layout.addWidget(actions_group)

        main_splitter.addWidget(filter_panel)

        # MIDDLE PANEL - Main table
        middle_panel = QWidget()
        middle_layout = QVBoxLayout(middle_panel)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        # Table widget - better checkbox handling than QTreeWidget
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(7)
        self.items_table.setHorizontalHeaderLabels([
            "✓", "Title", "URL", "Folder", "Browser/Profile", "Dead Link", "Duplicate"
        ])
        self.items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setSortingEnabled(True)
        self.items_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_table.customContextMenuRequested.connect(self.show_context_menu)
        self.items_table.cellChanged.connect(self.on_cell_changed)
        self.items_table.itemSelectionChanged.connect(self.on_selection_changed)

        # Column sizes
        header = self.items_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 30)  # Checkbox - narrow
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 200)  # Title
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # URL stretches
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 120)  # Folder
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(4, 130)  # Browser/Profile
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(5, 100)  # Dead Link
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(6, 80)  # Duplicate

        middle_layout.addWidget(self.items_table)

        # Count and selection info
        info_layout = QHBoxLayout()
        self.count_label = QLabel("0 items")
        info_layout.addWidget(self.count_label)
        info_layout.addStretch()
        self.selection_label = QLabel("0 selected for deletion")
        self.selection_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.selection_label)
        middle_layout.addLayout(info_layout)

        main_splitter.addWidget(middle_panel)

        # RIGHT PANEL - Preview
        preview_panel = QWidget()
        preview_panel.setMinimumWidth(250)
        preview_panel.setMaximumWidth(350)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_group = QGroupBox("Selected for Deletion")
        preview_inner = QVBoxLayout(preview_group)

        # Preview tree
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["Item", "Details"])
        self.preview_tree.setRootIsDecorated(True)
        self.preview_tree.setAlternatingRowColors(True)
        preview_header = self.preview_tree.header()
        preview_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        preview_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        preview_header.resizeSection(1, 80)
        preview_inner.addWidget(self.preview_tree)

        # Summary
        self.summary_label = QLabel("No items selected")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        preview_inner.addWidget(self.summary_label)

        preview_layout.addWidget(preview_group)
        main_splitter.addWidget(preview_panel)

        # Set splitter proportions
        main_splitter.setSizes([300, 800, 300])
        layout.addWidget(main_splitter, 1)

        # Bottom buttons
        self._create_bottom_buttons(layout)

    def _create_bottom_buttons(self, layout):
        """Create the bottom button bar."""
        # Row 1: Export options
        export_layout = QHBoxLayout()
        export_layout.addWidget(QLabel("<b>Sync-Safe Deletion:</b>"))

        self.copy_ids_btn = QPushButton("Copy IDs to Clipboard")
        self.copy_ids_btn.clicked.connect(self.copy_ids_to_clipboard)
        self.copy_ids_btn.setEnabled(False)
        export_layout.addWidget(self.copy_ids_btn)

        self.save_ids_btn = QPushButton("Save IDs to File...")
        self.save_ids_btn.clicked.connect(self.save_ids_to_file)
        self.save_ids_btn.setEnabled(False)
        export_layout.addWidget(self.save_ids_btn)

        help_btn = QPushButton("?")
        help_btn.setFixedWidth(25)
        help_btn.clicked.connect(self.show_extension_help)
        export_layout.addWidget(help_btn)

        export_layout.addStretch()
        layout.addLayout(export_layout)

        # Row 2: Main actions
        button_layout = QHBoxLayout()

        restore_btn = QPushButton("Restore from Backup...")
        restore_btn.clicked.connect(self.show_restore_dialog)
        button_layout.addWidget(restore_btn)

        refresh_btn = QPushButton("Refresh from Browsers")
        refresh_btn.clicked.connect(self.refresh_from_browsers)
        button_layout.addWidget(refresh_btn)

        button_layout.addStretch()

        self.delete_btn = QPushButton("Delete (File-Based)")
        self.delete_btn.setStyleSheet(
            "background-color: #6c757d; color: white; font-weight: bold; padding: 8px 16px;"
        )
        self.delete_btn.clicked.connect(self.start_deletion)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def load_data(self):
        """Load all data from the database."""
        self.all_items.clear()
        self.selected_for_deletion.clear()
        self.keep_in_group.clear()
        self.visible_items.clear()

        # Load bookmark data
        bookmark_data = self._load_bookmark_data()

        # Load dead links
        self._load_dead_links(bookmark_data)

        # Load duplicates
        self._load_duplicates(bookmark_data, "exact")
        self._load_duplicates(bookmark_data, "similar")

        # Build filter values
        self._populate_filters()

        # Apply filters and show items
        self.apply_filters()

    def _load_bookmark_data(self) -> Dict[int, dict]:
        """Load bookmark data with profile and folder information."""
        data = {}
        cursor = self.db.execute("""
            SELECT
                b.bookmark_id,
                b.url,
                b.title,
                b.browser_bookmark_id,
                bp.browser_name,
                bp.profile_display_name,
                bp.profile_path,
                f.browser_folder_path
            FROM bookmarks b
            JOIN browser_profiles bp ON b.browser_profile_id = bp.browser_profile_id
            LEFT JOIN folders f ON b.folder_id = f.folder_id
        """)

        for row in cursor.fetchall():
            data[row[0]] = {
                'bookmark_id': row[0],
                'url': row[1],
                'title': row[2] or "(no title)",
                'browser_bookmark_id': row[3],
                'browser_name': row[4],
                'profile_name': row[5],
                'profile_path': row[6],
                'folder_path': row[7] or "Bookmarks Bar"
            }
        return data

    def _load_dead_links(self, bookmark_data: Dict[int, dict]):
        """Load dead links from the database."""
        cursor = self.db.execute("""
            SELECT DISTINCT check_run_id FROM dead_links
            ORDER BY checked_at DESC LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return

        check_run_id = row[0]

        cursor = self.db.execute("""
            SELECT bookmark_id, status_code, error_message
            FROM dead_links
            WHERE check_run_id = ?
        """, (check_run_id,))

        for row in cursor.fetchall():
            bookmark_id = row[0]
            status_code = row[1]
            error_message = row[2]

            if bookmark_id not in bookmark_data:
                continue

            dead_link_detail = self._format_dead_link_detail(status_code, error_message)

            bd = bookmark_data[bookmark_id]
            self.all_items[bookmark_id] = DeletionItem(
                bookmark_id=bookmark_id,
                browser_bookmark_id=bd['browser_bookmark_id'],
                browser_name=bd['browser_name'],
                profile_path=bd['profile_path'],
                profile_name=bd['profile_name'],
                url=bd['url'],
                title=bd['title'],
                reason="dead_link",
                folder_path=bd['folder_path'],
                dead_link_detail=dead_link_detail
            )

    def _load_duplicates(self, bookmark_data: Dict[int, dict], match_type: str):
        """Load duplicate groups from the database."""
        cursor = self.db.execute("""
            SELECT DISTINCT check_run_id FROM duplicate_groups
            WHERE match_type = ?
            ORDER BY created_at DESC LIMIT 1
        """, (match_type,))
        row = cursor.fetchone()
        if not row:
            return

        check_run_id = row[0]

        cursor = self.db.execute("""
            SELECT duplicate_group_id, normalized_url
            FROM duplicate_groups
            WHERE check_run_id = ? AND match_type = ?
        """, (check_run_id, match_type))

        for group_id, normalized_url in cursor.fetchall():
            cursor2 = self.db.execute("""
                SELECT bookmark_id FROM duplicate_group_members
                WHERE duplicate_group_id = ?
            """, (group_id,))

            bookmark_ids = [r[0] for r in cursor2.fetchall()]
            valid_ids = [bid for bid in bookmark_ids if bid in bookmark_data]

            if len(valid_ids) < 2:
                continue

            for bookmark_id in valid_ids:
                if bookmark_id in self.all_items:
                    existing = self.all_items[bookmark_id]
                    if match_type not in existing.reason:
                        existing.reason += f",{match_type}_duplicate"
                    existing.group_id = group_id
                    continue

                bd = bookmark_data[bookmark_id]
                self.all_items[bookmark_id] = DeletionItem(
                    bookmark_id=bookmark_id,
                    browser_bookmark_id=bd['browser_bookmark_id'],
                    browser_name=bd['browser_name'],
                    profile_path=bd['profile_path'],
                    profile_name=bd['profile_name'],
                    url=bd['url'],
                    title=bd['title'],
                    reason=f"{match_type}_duplicate",
                    group_id=group_id,
                    folder_path=bd['folder_path']
                )

            # Choose which to keep - prefer non-dead-links
            keep_id = None
            for bookmark_id in valid_ids:
                item = self.all_items.get(bookmark_id)
                if item and "dead_link" not in item.reason:
                    keep_id = bookmark_id
                    break

            if keep_id is not None:
                self.keep_in_group[group_id] = keep_id

    def _format_dead_link_detail(self, status_code: Optional[int], error_message: Optional[str]) -> str:
        """Format dead link details."""
        if status_code:
            descriptions = {
                400: "400 Bad Request", 401: "401 Unauthorized", 403: "403 Forbidden",
                404: "404 Not Found", 405: "405 Method Not Allowed", 408: "408 Timeout",
                410: "410 Gone", 429: "429 Too Many Requests", 500: "500 Server Error",
                502: "502 Bad Gateway", 503: "503 Unavailable", 504: "504 Gateway Timeout",
            }
            return descriptions.get(status_code, f"HTTP {status_code}")

        if error_message:
            msg = error_message.lower()
            if "timeout" in msg:
                return "Connection Timeout"
            elif "connection refused" in msg:
                return "Connection Refused"
            elif "dns" in msg or "getaddrinfo" in msg:
                return "DNS Lookup Failed"
            elif "ssl" in msg or "certificate" in msg:
                return "SSL Error"
            return error_message[:30]

        return "Unknown Error"

    def _populate_filters(self):
        """Populate filter widgets with values from data."""
        browsers = set()
        profiles = set()
        domains = set()
        tlds = set()
        subdomains = set()
        dead_errors = set()
        dup_types = set()
        folders = set()

        for item in self.all_items.values():
            browsers.add(item.browser_name)
            profiles.add(f"{item.browser_name}/{item.profile_name}")
            if item.url_domain:
                domains.add(item.url_domain)
            if item.url_tld:
                tlds.add(item.url_tld)
            if item.url_subdomain:
                subdomains.add(item.url_subdomain)
            if item.dead_link_detail:
                dead_errors.add(item.dead_link_detail)
            if "exact_duplicate" in item.reason:
                dup_types.add("Exact")
            if "similar_duplicate" in item.reason:
                dup_types.add("Similar")
            if item.folder_path:
                folders.add(item.folder_path)

        self.browser_filter.set_values(list(browsers))
        self.profile_filter.set_values(list(profiles))
        self.domain_filter.set_values(list(domains))
        self.tld_filter.set_values(list(tlds))
        self.subdomain_filter.set_values(list(subdomains))
        self.dead_link_filter.set_values(list(dead_errors))
        self.duplicate_filter.set_values(list(dup_types))
        self.folder_filter.set_values(list(folders))

    def apply_filters(self):
        """Apply all filters and rebuild the table."""
        self.items_table.blockSignals(True)
        self.items_table.setSortingEnabled(False)
        self.items_table.setRowCount(0)
        self.visible_items.clear()

        # Get filter selections
        show_dead = self.dead_links_check.isChecked()
        show_exact = self.exact_dups_check.isChecked()
        show_similar = self.similar_dups_check.isChecked()

        browser_sel = self.browser_filter.get_selected()
        profile_sel = self.profile_filter.get_selected()
        domain_sel = self.domain_filter.get_selected()
        tld_sel = self.tld_filter.get_selected()
        subdomain_sel = self.subdomain_filter.get_selected()
        dead_sel = self.dead_link_filter.get_selected()
        dup_sel = self.duplicate_filter.get_selected()
        folder_sel = self.folder_filter.get_selected()

        for item in self.all_items.values():
            # Category filter
            passes_cat = False
            if "dead_link" in item.reason and show_dead:
                passes_cat = True
            if "exact_duplicate" in item.reason and show_exact:
                passes_cat = True
            if "similar_duplicate" in item.reason and show_similar:
                passes_cat = True
            if not passes_cat:
                continue

            # Browser filter
            if browser_sel and item.browser_name not in browser_sel:
                continue

            # Profile filter
            profile_key = f"{item.browser_name}/{item.profile_name}"
            if profile_sel and profile_key not in profile_sel:
                continue

            # Domain filters
            if domain_sel and item.url_domain not in domain_sel:
                continue
            if tld_sel and item.url_tld not in tld_sel:
                continue
            if subdomain_sel and (not item.url_subdomain or item.url_subdomain not in subdomain_sel):
                continue

            # Dead link filter
            if dead_sel and (not item.dead_link_detail or item.dead_link_detail not in dead_sel):
                continue

            # Duplicate type filter
            if dup_sel:
                item_dup_type = None
                if "exact_duplicate" in item.reason:
                    item_dup_type = "Exact"
                elif "similar_duplicate" in item.reason:
                    item_dup_type = "Similar"
                if not item_dup_type or item_dup_type not in dup_sel:
                    continue

            # Folder filter
            if folder_sel and (not item.folder_path or item.folder_path not in folder_sel):
                continue

            # Item passed all filters - add to table
            self._add_table_row(item)
            self.visible_items.add(item.bookmark_id)

        self.items_table.setSortingEnabled(True)
        self.items_table.blockSignals(False)

        self.count_label.setText(f"{len(self.visible_items)} items shown")
        self.update_preview()

    def _add_table_row(self, item: DeletionItem):
        """Add a row to the table for an item."""
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)

        is_kept = item.group_id is not None and self.keep_in_group.get(item.group_id) == item.bookmark_id

        # Checkbox
        check_item = QTableWidgetItem()
        check_item.setData(Qt.ItemDataRole.UserRole, item.bookmark_id)
        check_item.setData(Qt.ItemDataRole.UserRole + 1, item.group_id)
        if is_kept:
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        else:
            check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            if item.bookmark_id in self.selected_for_deletion:
                check_item.setCheckState(Qt.CheckState.Checked)
            else:
                check_item.setCheckState(Qt.CheckState.Unchecked)
        self.items_table.setItem(row, 0, check_item)

        # Title
        title_item = QTableWidgetItem(item.title[:60])
        title_item.setToolTip(item.title)
        self.items_table.setItem(row, 1, title_item)

        # URL
        url_item = QTableWidgetItem(item.url)
        url_item.setToolTip(item.url)
        self.items_table.setItem(row, 2, url_item)

        # Folder
        folder_item = QTableWidgetItem(item.folder_path or "")
        self.items_table.setItem(row, 3, folder_item)

        # Browser/Profile
        bp_item = QTableWidgetItem(f"{item.browser_name}/{item.profile_name}")
        self.items_table.setItem(row, 4, bp_item)

        # Dead Link
        dead_item = QTableWidgetItem(item.dead_link_detail or "")
        if item.dead_link_detail:
            if "404" in item.dead_link_detail:
                dead_item.setForeground(QBrush(QColor(220, 53, 69)))
            elif "Timeout" in item.dead_link_detail:
                dead_item.setForeground(QBrush(QColor(255, 153, 0)))
        self.items_table.setItem(row, 5, dead_item)

        # Duplicate
        if is_kept:
            dup_item = QTableWidgetItem("✓ KEEP")
            dup_item.setBackground(QBrush(QColor(200, 255, 200)))
        elif "exact_duplicate" in item.reason:
            dup_item = QTableWidgetItem("Exact")
            dup_item.setForeground(QBrush(QColor(220, 53, 69)))
        elif "similar_duplicate" in item.reason:
            dup_item = QTableWidgetItem("Similar")
            dup_item.setForeground(QBrush(QColor(255, 153, 0)))
        else:
            dup_item = QTableWidgetItem("")
        self.items_table.setItem(row, 6, dup_item)

    def on_cell_changed(self, row: int, col: int):
        """Handle cell change (checkbox toggle)."""
        if col != 0:
            return

        item = self.items_table.item(row, 0)
        if item is None:
            return

        bookmark_id = item.data(Qt.ItemDataRole.UserRole)
        if bookmark_id is None:
            return

        # Check if this is a KEEP item
        group_id = item.data(Qt.ItemDataRole.UserRole + 1)
        if group_id is not None and self.keep_in_group.get(group_id) == bookmark_id:
            return

        if item.checkState() == Qt.CheckState.Checked:
            self.selected_for_deletion.add(bookmark_id)
        else:
            self.selected_for_deletion.discard(bookmark_id)

        self.update_preview()

    def on_selection_changed(self):
        """Handle row selection change."""
        selected_count = len(self.items_table.selectedItems()) // self.items_table.columnCount()
        if selected_count > 0:
            self.selection_label.setText(f"{len(self.selected_for_deletion)} selected for deletion | {selected_count} rows highlighted")
        else:
            self.selection_label.setText(f"{len(self.selected_for_deletion)} selected for deletion")

    def show_context_menu(self, position):
        """Show context menu."""
        item = self.items_table.itemAt(position)
        if item is None:
            return

        row = item.row()
        check_item = self.items_table.item(row, 0)
        if check_item is None:
            return

        bookmark_id = check_item.data(Qt.ItemDataRole.UserRole)
        group_id = check_item.data(Qt.ItemDataRole.UserRole + 1)
        url_item = self.items_table.item(row, 2)
        url = url_item.text() if url_item else ""

        menu = QMenu(self)

        # Check/uncheck
        if check_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            if check_item.checkState() == Qt.CheckState.Checked:
                action = menu.addAction("Uncheck (Don't Delete)")
                action.triggered.connect(lambda: self._toggle_row(row, False))
            else:
                action = menu.addAction("Check (Mark for Deletion)")
                action.triggered.connect(lambda: self._toggle_row(row, True))

        # Set as KEEP
        if group_id is not None:
            is_keep = self.keep_in_group.get(group_id) == bookmark_id
            if not is_keep:
                menu.addSeparator()
                keep_action = menu.addAction("✓ Set as KEEP")
                keep_action.triggered.connect(lambda: self._set_as_keep(bookmark_id, group_id))

        # URL actions
        menu.addSeparator()
        open_action = menu.addAction("Open in Browser")
        open_action.triggered.connect(lambda: self._open_url(url))

        copy_action = menu.addAction("Copy URL")
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(url))

        # Thumbnail
        menu.addSeparator()
        thumb_action = menu.addAction("Generate Thumbnail")
        thumb_action.triggered.connect(lambda: self._generate_thumbnail(url))

        menu.exec(self.items_table.viewport().mapToGlobal(position))

    def _toggle_row(self, row: int, checked: bool):
        """Toggle a row's checkbox."""
        item = self.items_table.item(row, 0)
        if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            self.items_table.blockSignals(True)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.items_table.blockSignals(False)

            bookmark_id = item.data(Qt.ItemDataRole.UserRole)
            if checked:
                self.selected_for_deletion.add(bookmark_id)
            else:
                self.selected_for_deletion.discard(bookmark_id)
            self.update_preview()

    def _set_as_keep(self, bookmark_id: int, group_id: int):
        """Set a bookmark as the one to keep in its group."""
        old_keep = self.keep_in_group.get(group_id)
        self.keep_in_group[group_id] = bookmark_id
        self.selected_for_deletion.discard(bookmark_id)

        if old_keep is not None and old_keep != bookmark_id:
            self.selected_for_deletion.add(old_keep)

        self.apply_filters()

    def _open_url(self, url: str):
        """Open URL in browser."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _generate_thumbnail(self, url: str):
        """Generate thumbnail for a single URL."""
        from ..services.thumbnail_service import get_thumbnail_service
        service = get_thumbnail_service()
        service.get_thumbnail(url, force_refresh=True)
        QMessageBox.information(self, "Thumbnail", f"Thumbnail generation started for:\n{url[:60]}...")

    def generate_thumbnails_for_visible(self):
        """Generate thumbnails for all visible items."""
        if not self.visible_items:
            QMessageBox.information(self, "No Items", "No items are currently visible.")
            return

        urls = [self.all_items[bid].url for bid in self.visible_items if bid in self.all_items]

        from .thumbnail_dialog import ThumbnailDialog
        dialog = ThumbnailDialog(urls, self)
        dialog.exec()

    def select_all_visible(self):
        """Select all visible items."""
        self.items_table.blockSignals(True)

        for row in range(self.items_table.rowCount()):
            item = self.items_table.item(row, 0)
            if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Checked)
                bookmark_id = item.data(Qt.ItemDataRole.UserRole)
                if bookmark_id:
                    self.selected_for_deletion.add(bookmark_id)

        self.items_table.blockSignals(False)
        self.update_preview()

    def deselect_all(self):
        """Deselect all items."""
        self.items_table.blockSignals(True)
        self.selected_for_deletion.clear()

        for row in range(self.items_table.rowCount()):
            item = self.items_table.item(row, 0)
            if item and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Unchecked)

        self.items_table.blockSignals(False)
        self.update_preview()

    def auto_select_duplicates(self):
        """Auto-select duplicates, keeping first non-dead in each group."""
        groups: Dict[int, List[DeletionItem]] = {}
        for item in self.all_items.values():
            if item.group_id is not None:
                if item.group_id not in groups:
                    groups[item.group_id] = []
                groups[item.group_id].append(item)

        for group_id, items in groups.items():
            if len(items) < 2:
                continue

            # Find first non-dead to keep
            keep_item = None
            for item in items:
                if "dead_link" not in item.reason:
                    keep_item = item
                    break

            if keep_item:
                self.keep_in_group[group_id] = keep_item.bookmark_id
                self.selected_for_deletion.discard(keep_item.bookmark_id)
                for item in items:
                    if item.bookmark_id != keep_item.bookmark_id:
                        self.selected_for_deletion.add(item.bookmark_id)
            else:
                # All are dead - select all
                for item in items:
                    self.selected_for_deletion.add(item.bookmark_id)

        self.apply_filters()

    def clear_all_filters(self):
        """Clear all filter selections."""
        self.browser_filter.clear_selection()
        self.profile_filter.clear_selection()
        self.domain_filter.clear_selection()
        self.tld_filter.clear_selection()
        self.subdomain_filter.clear_selection()
        self.dead_link_filter.clear_selection()
        self.duplicate_filter.clear_selection()
        self.folder_filter.clear_selection()

    def update_preview(self):
        """Update the preview panel."""
        self.preview_tree.clear()

        count = len(self.selected_for_deletion)
        self.selection_label.setText(f"{count} selected for deletion")

        # Update button states
        has_selection = count > 0
        self.delete_btn.setEnabled(has_selection)
        self.copy_ids_btn.setEnabled(has_selection)
        self.save_ids_btn.setEnabled(has_selection)

        if not self.selected_for_deletion:
            self.summary_label.setText("No items selected for deletion.\n\nUse 'Auto-Select Duplicates' to quickly select duplicates.")
            return

        # Group by browser -> profile
        by_browser: Dict[str, Dict[str, List[DeletionItem]]] = {}
        for bid in self.selected_for_deletion:
            if bid not in self.all_items:
                continue
            item = self.all_items[bid]
            if item.browser_name not in by_browser:
                by_browser[item.browser_name] = {}
            if item.profile_name not in by_browser[item.browser_name]:
                by_browser[item.browser_name][item.profile_name] = []
            by_browser[item.browser_name][item.profile_name].append(item)

        # Build tree
        for browser, profiles in sorted(by_browser.items()):
            browser_count = sum(len(items) for items in profiles.values())
            browser_item = QTreeWidgetItem([f"🌐 {browser}", f"{browser_count}"])
            browser_item.setExpanded(True)

            for profile, items in sorted(profiles.items()):
                profile_item = QTreeWidgetItem([f"👤 {profile}", f"{len(items)}"])
                for item in items[:15]:
                    title = item.title[:35] + "..." if len(item.title) > 35 else item.title
                    bookmark_item = QTreeWidgetItem([f"📄 {title}", ""])
                    bookmark_item.setToolTip(0, f"{item.title}\n{item.url}")
                    profile_item.addChild(bookmark_item)
                if len(items) > 15:
                    more = QTreeWidgetItem([f"... +{len(items) - 15} more", ""])
                    profile_item.addChild(more)
                profile_item.setExpanded(True)
                browser_item.addChild(profile_item)

            self.preview_tree.addTopLevelItem(browser_item)

        # Summary
        self.summary_label.setText(f"Total: {count} bookmarks to delete")

    def show_restore_dialog(self):
        """Show restore dialog."""
        from .restore_backup_dialog import RestoreBackupDialog
        dialog = RestoreBackupDialog(self.modifier_service.backup_dir, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Restore Complete", "Bookmarks restored. Restart browser to see changes.")

    def refresh_from_browsers(self):
        """Refresh from browser files."""
        reply = QMessageBox.question(
            self, "Refresh",
            "Re-scan browser bookmark files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.load_data()
            QMessageBox.information(self, "Refreshed", "Data reloaded from database.")

    def start_deletion(self):
        """Start deletion process."""
        if not self.selected_for_deletion:
            return

        selected_items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]
        affected_browsers = {item.browser_name for item in selected_items}

        # Check running browsers
        running = BrowserProcessService.get_running_browsers()
        running_affected = [b for b in running if b.browser_name in affected_browsers]

        if running_affected:
            from .browser_close_dialog import BrowserCloseDialog
            dialog = BrowserCloseDialog(running_affected, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            still_running = [
                b.browser_name for b in BrowserProcessService.get_running_browsers()
                if b.browser_name in affected_browsers
            ]
            if still_running:
                QMessageBox.warning(self, "Browsers Running", f"Still running: {', '.join(still_running)}")
                return

        # Confirm
        total = len(selected_items)
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete {total} bookmark{'s' if total != 1 else ''} from browsers?\n\nBackups will be created.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.perform_deletion(selected_items)

    def perform_deletion(self, items: List[DeletionItem]):
        """Perform the deletion."""
        bookmarks_to_delete = [
            BookmarkToDelete(
                bookmark_id=item.bookmark_id,
                browser_bookmark_id=item.browser_bookmark_id,
                browser_name=item.browser_name,
                profile_path=Path(item.profile_path),
                profile_name=item.profile_name,
                url=item.url,
                title=item.title,
                reason=item.reason
            )
            for item in items
        ]

        progress = QProgressDialog("Deleting...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        try:
            results = self.modifier_service.delete_bookmarks(bookmarks_to_delete, create_backup=True)
            progress.close()

            success_count = sum(r.bookmarks_deleted for r in results if r.success)
            QMessageBox.information(self, "Done", f"Deleted {success_count} bookmarks.\n\nBackups saved to:\n{self.modifier_service.backup_dir}")

            # Remove from database
            for item in items:
                try:
                    self.db.execute("DELETE FROM bookmarks WHERE bookmark_id = ?", (item.bookmark_id,))
                except Exception:
                    pass
            self.db.commit()

            self.load_data()

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", str(e))

    def _get_selected_ids_text(self) -> str:
        """Get browser bookmark IDs as text."""
        items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]
        return '\n'.join(str(item.browser_bookmark_id) for item in items)

    def _create_backups_for_selected(self) -> str:
        """Create backups for selected profiles."""
        items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]
        profiles = {}
        for item in items:
            key = (item.profile_path, item.browser_name, item.profile_name)
            profiles[key] = key

        results = []
        for profile_path, browser_name, profile_name in profiles.keys():
            try:
                self.modifier_service.create_backup(Path(profile_path), browser_name, profile_name)
                results.append(f"  • {browser_name}/{profile_name}")
            except Exception as e:
                results.append(f"  • {browser_name}/{profile_name}: FAILED")
        return "\n".join(results)

    def copy_ids_to_clipboard(self):
        """Copy IDs to clipboard."""
        ids_text = self._get_selected_ids_text()
        if not ids_text:
            return

        backup_info = self._create_backups_for_selected()
        QApplication.clipboard().setText(ids_text)

        count = len(ids_text.strip().split('\n'))
        QMessageBox.information(self, "Copied",
            f"{count} ID(s) copied to clipboard.\n\nBackups:\n{backup_info}\n\nLocation: {self.modifier_service.backup_dir}")

    def save_ids_to_file(self):
        """Save IDs to file."""
        from PyQt6.QtWidgets import QFileDialog

        ids_text = self._get_selected_ids_text()
        if not ids_text:
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Save IDs", "bookmark_ids.txt", "Text Files (*.txt)")
        if not filename:
            return

        backup_info = self._create_backups_for_selected()

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Bookmark IDs to delete\n")
            f.write(ids_text)

        QMessageBox.information(self, "Saved", f"IDs saved to {filename}\n\nBackups:\n{backup_info}")

    def show_extension_help(self):
        """Show extension help."""
        QMessageBox.information(self, "Browser Extension",
            "Use the Bookmark Manager Helper extension for sync-safe deletion.\n\n"
            "1. Copy IDs or save to file\n"
            "2. Open extension in browser\n"
            "3. Paste/load IDs and delete\n\n"
            "This uses Chrome's Bookmarks API which syncs properly.")
