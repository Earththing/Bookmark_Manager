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
    QAbstractItemView, QApplication, QScrollArea, QSizePolicy
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


class CheckboxFilterWidget(QWidget):
    """A filter widget with checkboxes for multi-select and search box."""

    filterChanged = pyqtSignal()

    def __init__(self, column_name: str, parent=None):
        super().__init__(parent)
        self.column_name = column_name
        self.all_values: List[str] = []
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.search_text = ""

        self.setup_ui()

    def setup_ui(self):
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header with column name and buttons
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(f"<b>{self.column_name}</b>")
        header_layout.addWidget(self.label)

        header_layout.addStretch()

        # Select All button
        self.select_all_btn = QToolButton()
        self.select_all_btn.setText("All")
        self.select_all_btn.setToolTip("Select all visible items")
        self.select_all_btn.setFixedSize(30, 20)
        self.select_all_btn.clicked.connect(self.select_all)
        header_layout.addWidget(self.select_all_btn)

        # Clear button
        self.clear_btn = QToolButton()
        self.clear_btn.setText("×")
        self.clear_btn.setToolTip("Clear filter (show all)")
        self.clear_btn.setFixedSize(20, 20)
        self.clear_btn.clicked.connect(self.clear_filter)
        header_layout.addWidget(self.clear_btn)

        layout.addLayout(header_layout)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to filter...")
        self.search_box.textChanged.connect(self._on_search_changed)
        self.search_box.setMaximumHeight(24)
        layout.addWidget(self.search_box)

        # Scrollable container for checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(120)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        self.checkbox_layout.setContentsMargins(2, 2, 2, 2)
        self.checkbox_layout.setSpacing(1)

        scroll_area.setWidget(self.checkbox_container)
        layout.addWidget(scroll_area)

        # Status label
        self.status_label = QLabel("All")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.status_label)

    def set_values(self, values: List[str]):
        """Set the available values for filtering."""
        # Remember which values were checked
        previously_checked = {v for v, cb in self.checkboxes.items() if cb.isChecked()}

        # Clear existing checkboxes
        for cb in self.checkboxes.values():
            cb.deleteLater()
        self.checkboxes.clear()

        self.all_values = sorted(set(values))

        # Create checkboxes
        for value in self.all_values:
            cb = QCheckBox(value[:35] + "..." if len(value) > 35 else value)
            cb.setToolTip(value)  # Full value in tooltip
            cb.setChecked(value in previously_checked)
            cb.stateChanged.connect(self._on_checkbox_changed)
            self.checkboxes[value] = cb
            self.checkbox_layout.addWidget(cb)

        # Apply search filter if active
        if self.search_text:
            self._apply_search_filter()

        self._update_status()

    def _on_search_changed(self, text: str):
        """Handle search text change."""
        self.search_text = text.lower()
        self._apply_search_filter()

    def _apply_search_filter(self):
        """Show/hide checkboxes based on search text."""
        for value, cb in self.checkboxes.items():
            if self.search_text:
                cb.setVisible(self.search_text in value.lower())
            else:
                cb.setVisible(True)

    def _on_checkbox_changed(self, state: int):
        """Handle checkbox state change."""
        self._update_status()
        self.filterChanged.emit()

    def _update_status(self):
        """Update the status label."""
        checked_count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        total = len(self.checkboxes)

        if checked_count == 0:
            self.status_label.setText("All (no filter)")
        elif checked_count == total:
            self.status_label.setText("All selected")
        else:
            self.status_label.setText(f"{checked_count} of {total} selected")

    def get_selected_values(self) -> Optional[Set[str]]:
        """Get the selected values, or None if none selected (no filter = show all)."""
        checked = {v for v, cb in self.checkboxes.items() if cb.isChecked()}
        if not checked:
            return None  # No filter - show all
        return checked

    def select_all(self):
        """Select all visible checkboxes."""
        for value, cb in self.checkboxes.items():
            if cb.isVisible():
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
        self._update_status()
        self.filterChanged.emit()

    def clear_filter(self):
        """Clear all selections (no filter = show all)."""
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

        # Column filter widgets (populated in setup_ui)
        self.filter_widgets: Dict[int, CheckboxFilterWidget] = {}

        # Column sort state
        self.sort_column: int = 1  # Default sort by title
        self.sort_ascending: bool = True

        # Track which items are currently visible after filtering
        self.visible_items: Set[int] = set()

        self.setWindowTitle("Delete Bookmarks from Browsers")
        self.setMinimumSize(1400, 800)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Warning banner - FIXED HEIGHT, won't stretch
        warning_frame = QFrame()
        warning_frame.setStyleSheet(
            "background-color: #fff3cd; border: 1px solid #ffc107; "
            "border-radius: 4px; padding: 8px;"
        )
        warning_frame.setFixedHeight(70)  # Fixed height - enough to read the warning
        warning_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        warning_layout = QHBoxLayout(warning_frame)
        warning_label = QLabel(
            "⚠️ <b>Warning:</b> This will permanently delete selected bookmarks "
            "from your browsers. Backups are created automatically before changes."
        )
        warning_label.setWordWrap(True)
        warning_layout.addWidget(warning_label)
        layout.addWidget(warning_frame)

        # Main content - splitter with filters on left, items in middle, preview on right
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Category and Browser Filters
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Category filter
        category_group = QGroupBox("Categories")
        category_layout = QVBoxLayout(category_group)

        self.dead_links_check = QCheckBox("Dead Links")
        self.dead_links_check.setChecked(True)
        self.dead_links_check.stateChanged.connect(self.apply_filters)
        category_layout.addWidget(self.dead_links_check)

        self.exact_dups_check = QCheckBox("Exact Duplicates")
        self.exact_dups_check.setChecked(True)
        self.exact_dups_check.stateChanged.connect(self.apply_filters)
        category_layout.addWidget(self.exact_dups_check)

        self.similar_dups_check = QCheckBox("Similar Duplicates")
        self.similar_dups_check.setChecked(True)
        self.similar_dups_check.stateChanged.connect(self.apply_filters)
        category_layout.addWidget(self.similar_dups_check)

        left_layout.addWidget(category_group)

        # Browser filter
        browser_group = QGroupBox("Browsers")
        browser_layout = QVBoxLayout(browser_group)

        self.browser_checks: Dict[str, QCheckBox] = {}
        self.browser_container = QWidget()
        self.browser_container_layout = QVBoxLayout(self.browser_container)
        self.browser_container_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.browser_container)

        left_layout.addWidget(browser_group)

        # Profile filter
        profile_group = QGroupBox("Profiles")
        profile_layout = QVBoxLayout(profile_group)

        self.profile_checks: Dict[str, QCheckBox] = {}
        self.profile_container = QWidget()
        self.profile_container_layout = QVBoxLayout(self.profile_container)
        self.profile_container_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_container)

        left_layout.addWidget(profile_group)

        left_layout.addStretch()

        # Quick actions
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QVBoxLayout(actions_group)

        select_all_btn = QPushButton("Select All Visible")
        select_all_btn.setToolTip("Select all items shown after filtering")
        select_all_btn.clicked.connect(self.select_all_visible)
        actions_layout.addWidget(select_all_btn)

        deselect_visible_btn = QPushButton("Deselect Visible")
        deselect_visible_btn.setToolTip("Deselect all items shown after filtering")
        deselect_visible_btn.clicked.connect(self.deselect_visible)
        actions_layout.addWidget(deselect_visible_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setToolTip("Deselect all items (including filtered out)")
        deselect_all_btn.clicked.connect(self.deselect_all)
        actions_layout.addWidget(deselect_all_btn)

        auto_select_btn = QPushButton("Auto-Select Duplicates")
        auto_select_btn.setToolTip("Keep first bookmark in each group, select rest for deletion")
        auto_select_btn.clicked.connect(self.auto_select_duplicates)
        actions_layout.addWidget(auto_select_btn)

        left_layout.addWidget(actions_group)

        main_splitter.addWidget(left_panel)

        # Middle panel - Column Filters and Tree view
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        # Filter bar with checkbox filters - horizontal layout
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px;")
        filter_frame_layout = QVBoxLayout(filter_frame)
        filter_frame_layout.setContentsMargins(8, 8, 8, 8)

        # Row 1: Title, Domain, TLD, Subdomain
        filter_row1 = QHBoxLayout()
        filter_row1.setSpacing(12)

        # Title filter
        title_filter = CheckboxFilterWidget("Title")
        title_filter.setMinimumWidth(140)
        title_filter.setMaximumWidth(180)
        title_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[1] = title_filter
        filter_row1.addWidget(title_filter)

        # Domain filter
        domain_filter = CheckboxFilterWidget("Domain")
        domain_filter.setMinimumWidth(140)
        domain_filter.setMaximumWidth(180)
        domain_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[100] = domain_filter
        filter_row1.addWidget(domain_filter)

        # TLD filter
        tld_filter = CheckboxFilterWidget("TLD")
        tld_filter.setMinimumWidth(100)
        tld_filter.setMaximumWidth(120)
        tld_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[101] = tld_filter
        filter_row1.addWidget(tld_filter)

        # Subdomain filter
        subdomain_filter = CheckboxFilterWidget("Subdomain")
        subdomain_filter.setMinimumWidth(120)
        subdomain_filter.setMaximumWidth(150)
        subdomain_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[102] = subdomain_filter
        filter_row1.addWidget(subdomain_filter)

        filter_row1.addStretch()
        filter_frame_layout.addLayout(filter_row1)

        # Row 2: Folder, Dead Link, Duplicate
        filter_row2 = QHBoxLayout()
        filter_row2.setSpacing(12)

        # Folder filter
        folder_filter = CheckboxFilterWidget("Folder")
        folder_filter.setMinimumWidth(140)
        folder_filter.setMaximumWidth(180)
        folder_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[2] = folder_filter
        filter_row2.addWidget(folder_filter)

        # Dead Link filter
        dead_link_filter = CheckboxFilterWidget("Dead Link Error")
        dead_link_filter.setMinimumWidth(140)
        dead_link_filter.setMaximumWidth(180)
        dead_link_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[5] = dead_link_filter
        filter_row2.addWidget(dead_link_filter)

        # Duplicate filter
        duplicate_filter = CheckboxFilterWidget("Duplicate Type")
        duplicate_filter.setMinimumWidth(120)
        duplicate_filter.setMaximumWidth(150)
        duplicate_filter.filterChanged.connect(self.apply_filters)
        self.filter_widgets[6] = duplicate_filter
        filter_row2.addWidget(duplicate_filter)

        filter_row2.addStretch()

        clear_filters_btn = QPushButton("Clear All Filters")
        clear_filters_btn.clicked.connect(self.clear_all_filters)
        filter_row2.addWidget(clear_filters_btn)

        filter_frame_layout.addLayout(filter_row2)

        middle_layout.addWidget(filter_frame)

        # Tree widget showing bookmarks - ALL columns interactive for resizing
        self.items_tree = QTreeWidget()
        self.items_tree.setHeaderLabels(["Select", "Title ▲", "Folder", "URL", "Browser/Profile", "Dead Link", "Duplicate"])
        self.items_tree.setColumnCount(7)
        self.items_tree.setRootIsDecorated(False)
        self.items_tree.setAlternatingRowColors(True)
        self.items_tree.setSortingEnabled(False)
        self.items_tree.setStyleSheet("""
            QTreeWidget::item:selected {
                background-color: #cce5ff;
                color: black;
            }
            QTreeWidget::item:selected:!active {
                background-color: #d4e9ff;
                color: black;
            }
            QTreeWidget::item:hover {
                background-color: #e8f4ff;
            }
        """)
        self.items_tree.itemChanged.connect(self.on_item_changed)
        self.items_tree.itemClicked.connect(self.on_item_clicked)
        self.items_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_tree.customContextMenuRequested.connect(self.show_context_menu)

        # Enable header click for sorting
        header = self.items_tree.header()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)

        # ALL columns are Interactive for manual resizing
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 60)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 180)  # Title
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 150)  # Folder
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, 350)  # URL - wider by default
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(4, 140)  # Browser/Profile
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(5, 120)  # Dead Link
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(6, 90)  # Duplicate

        # Allow user to resize columns by dragging
        header.setStretchLastSection(True)

        middle_layout.addWidget(self.items_tree, 1)  # Give it stretch factor

        # Count label
        self.count_label = QLabel("0 items")
        middle_layout.addWidget(self.count_label)

        main_splitter.addWidget(middle_widget)

        # Right panel - Preview as Tree
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_group = QGroupBox("Selected for Deletion")
        preview_inner = QVBoxLayout(preview_group)

        # Preview tree widget - hierarchical view of selected items
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["Item", "Details"])
        self.preview_tree.setColumnCount(2)
        self.preview_tree.setRootIsDecorated(True)
        self.preview_tree.setAlternatingRowColors(True)
        self.preview_tree.setMinimumWidth(280)

        preview_header = self.preview_tree.header()
        preview_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        preview_header.resizeSection(0, 200)
        preview_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        preview_inner.addWidget(self.preview_tree)

        # Summary label
        self.summary_label = QLabel("No items selected")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
        preview_inner.addWidget(self.summary_label)

        preview_layout.addWidget(preview_group)

        main_splitter.addWidget(preview_widget)

        # Set splitter proportions
        main_splitter.setSizes([180, 800, 300])

        layout.addWidget(main_splitter, 1)  # Give splitter stretch factor

        # Bottom buttons - Row 1: Export for Extension
        export_layout = QHBoxLayout()

        export_label = QLabel("<b>For Sync-Safe Deletion:</b>")
        export_layout.addWidget(export_label)

        self.copy_ids_btn = QPushButton("Copy IDs to Clipboard")
        self.copy_ids_btn.setToolTip("Copy bookmark IDs for use with the browser extension")
        self.copy_ids_btn.clicked.connect(self.copy_ids_to_clipboard)
        self.copy_ids_btn.setEnabled(False)
        export_layout.addWidget(self.copy_ids_btn)

        self.save_ids_btn = QPushButton("Save IDs to File...")
        self.save_ids_btn.setToolTip("Save bookmark IDs to a file for use with the browser extension")
        self.save_ids_btn.clicked.connect(self.save_ids_to_file)
        self.save_ids_btn.setEnabled(False)
        export_layout.addWidget(self.save_ids_btn)

        extension_help_btn = QPushButton("?")
        extension_help_btn.setFixedWidth(30)
        extension_help_btn.setToolTip("Help with browser extension")
        extension_help_btn.clicked.connect(self.show_extension_help)
        export_layout.addWidget(extension_help_btn)

        export_layout.addStretch()

        layout.addLayout(export_layout)

        # Bottom buttons - Row 2: Main actions
        button_layout = QHBoxLayout()

        restore_btn = QPushButton("Restore from Backup...")
        restore_btn.clicked.connect(self.show_restore_dialog)
        button_layout.addWidget(restore_btn)

        refresh_btn = QPushButton("Refresh from Browsers")
        refresh_btn.setToolTip(
            "Re-scan browser bookmark files and update the database.\n"
            "Use after deleting bookmarks via the extension."
        )
        refresh_btn.clicked.connect(self.refresh_from_browsers)
        button_layout.addWidget(refresh_btn)

        button_layout.addStretch()

        self.delete_btn = QPushButton("Delete (File-Based)")
        self.delete_btn.setStyleSheet(
            "background-color: #6c757d; color: white; font-weight: bold; padding: 8px 16px;"
        )
        self.delete_btn.setToolTip(
            "Delete by modifying bookmark files directly.\n"
            "Warning: May not sync properly - bookmarks could reappear!"
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

        # Reset filter widgets
        for filter_widget in self.filter_widgets.values():
            filter_widget.clear_filter()

        # Load bookmark data with profile info
        bookmark_data = self._load_bookmark_data()

        # Load dead links
        self._load_dead_links(bookmark_data)

        # Load duplicates
        self._load_duplicates(bookmark_data, "exact")
        self._load_duplicates(bookmark_data, "similar")

        # Build filter checkboxes
        self._build_filter_checkboxes()

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
        # Get the most recent check run
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

            # Build a short description of why it's dead
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

        # Get groups
        cursor = self.db.execute("""
            SELECT duplicate_group_id, normalized_url
            FROM duplicate_groups
            WHERE check_run_id = ? AND match_type = ?
        """, (check_run_id, match_type))

        for group_id, normalized_url in cursor.fetchall():
            # Get bookmarks in group
            cursor2 = self.db.execute("""
                SELECT bookmark_id FROM duplicate_group_members
                WHERE duplicate_group_id = ?
            """, (group_id,))

            bookmark_ids = [r[0] for r in cursor2.fetchall()]
            valid_ids = [bid for bid in bookmark_ids if bid in bookmark_data]

            if len(valid_ids) < 2:
                continue

            # Process each bookmark in the group first
            for bookmark_id in valid_ids:
                # Skip if already in items (e.g., also a dead link)
                if bookmark_id in self.all_items:
                    # Update reason to include duplicate
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

            # Now choose which one to keep - prefer non-dead-links
            keep_id = None
            for bookmark_id in valid_ids:
                item = self.all_items.get(bookmark_id)
                if item and "dead_link" not in item.reason:
                    keep_id = bookmark_id
                    break

            # If all are dead links, don't auto-keep any (let user decide)
            if keep_id is not None:
                self.keep_in_group[group_id] = keep_id

    def _format_dead_link_detail(self, status_code: Optional[int], error_message: Optional[str]) -> str:
        """Format dead link details into a short, descriptive string."""
        if status_code:
            status_descriptions = {
                400: "400 Bad Request",
                401: "401 Unauthorized",
                403: "403 Forbidden",
                404: "404 Not Found",
                405: "405 Method Not Allowed",
                408: "408 Timeout",
                410: "410 Gone",
                429: "429 Too Many Requests",
                500: "500 Server Error",
                502: "502 Bad Gateway",
                503: "503 Unavailable",
                504: "504 Gateway Timeout",
            }
            if status_code in status_descriptions:
                return status_descriptions[status_code]
            elif 400 <= status_code < 500:
                return f"{status_code} Client Error"
            elif 500 <= status_code < 600:
                return f"{status_code} Server Error"
            else:
                return f"HTTP {status_code}"

        if error_message:
            msg = error_message.lower()
            if "timeout" in msg or "timed out" in msg:
                return "Connection Timeout"
            elif "connection refused" in msg:
                return "Connection Refused"
            elif "no such host" in msg or "name resolution" in msg or "dns" in msg or "getaddrinfo" in msg:
                return "DNS Lookup Failed"
            elif "ssl" in msg or "certificate" in msg:
                return "SSL/Certificate Error"
            elif "connection reset" in msg:
                return "Connection Reset"
            elif "too many redirects" in msg:
                return "Too Many Redirects"
            elif "connection error" in msg or "connect error" in msg:
                return "Connection Error"
            else:
                if len(error_message) > 30:
                    return error_message[:27] + "..."
                return error_message

        return "Unknown Error"

    def _build_filter_checkboxes(self):
        """Build browser and profile filter checkboxes."""
        # Clear existing
        for check in self.browser_checks.values():
            check.deleteLater()
        self.browser_checks.clear()

        for check in self.profile_checks.values():
            check.deleteLater()
        self.profile_checks.clear()

        # Collect browsers and profiles
        browsers = set()
        profiles = set()
        for item in self.all_items.values():
            browsers.add(item.browser_name)
            profiles.add(f"{item.browser_name}/{item.profile_name}")

        # Create browser checkboxes
        for browser in sorted(browsers):
            check = QCheckBox(browser)
            check.setChecked(True)
            check.stateChanged.connect(lambda state, b=browser: self.on_browser_check_changed(b, state))
            self.browser_checks[browser] = check
            self.browser_container_layout.addWidget(check)

        # Create profile checkboxes
        for profile in sorted(profiles):
            check = QCheckBox(profile)
            check.setChecked(True)
            check.stateChanged.connect(lambda state, p=profile: self.on_profile_check_changed(p, state))
            self.profile_checks[profile] = check
            self.profile_container_layout.addWidget(check)

    def on_browser_check_changed(self, browser_name: str, state: int):
        """Handle browser checkbox change."""
        is_checked = state == Qt.CheckState.Checked.value

        for profile_key, check in self.profile_checks.items():
            if profile_key.startswith(f"{browser_name}/"):
                check.blockSignals(True)
                check.setChecked(is_checked)
                check.blockSignals(False)

        self.apply_filters()

    def on_profile_check_changed(self, profile_key: str, state: int):
        """Handle profile checkbox change."""
        is_checked = state == Qt.CheckState.Checked.value
        browser_name = profile_key.split("/")[0]

        if is_checked:
            browser_check = self.browser_checks.get(browser_name)
            if browser_check and not browser_check.isChecked():
                browser_check.blockSignals(True)
                browser_check.setChecked(True)
                browser_check.blockSignals(False)
        else:
            all_unchecked = True
            for pk, check in self.profile_checks.items():
                if pk.startswith(f"{browser_name}/") and check.isChecked():
                    all_unchecked = False
                    break

            if all_unchecked:
                browser_check = self.browser_checks.get(browser_name)
                if browser_check:
                    browser_check.blockSignals(True)
                    browser_check.setChecked(False)
                    browser_check.blockSignals(False)

        self.apply_filters()

    def apply_filters(self):
        """Apply filters and rebuild the tree."""
        self.items_tree.blockSignals(True)
        self.items_tree.clear()
        self.visible_items.clear()

        # Get active category filters
        show_dead = self.dead_links_check.isChecked()
        show_exact = self.exact_dups_check.isChecked()
        show_similar = self.similar_dups_check.isChecked()

        active_browsers = {name for name, check in self.browser_checks.items() if check.isChecked()}
        active_profiles = {name for name, check in self.profile_checks.items() if check.isChecked()}

        # Collect items that pass filters
        filtered_items: List[DeletionItem] = []

        for item in self.all_items.values():
            profile_key = f"{item.browser_name}/{item.profile_name}"
            if item.browser_name not in active_browsers:
                continue
            if profile_key not in active_profiles:
                continue

            # Check category filter
            passes_category = False
            if "dead_link" in item.reason and show_dead:
                passes_category = True
            if "exact_duplicate" in item.reason and show_exact:
                passes_category = True
            if "similar_duplicate" in item.reason and show_similar:
                passes_category = True

            if not passes_category:
                continue

            # Check column filters
            if not self._passes_column_filters(item):
                continue

            filtered_items.append(item)

        # Sort items
        filtered_items = self._sort_items(filtered_items)

        # Update filter widgets with available values
        self._update_filter_widgets(filtered_items)

        # Add items to tree
        for item in filtered_items:
            is_duplicate = "duplicate" in item.reason
            is_kept = item.group_id is not None and self.keep_in_group.get(item.group_id) == item.bookmark_id
            tree_item = self._create_tree_item(item, is_duplicate=is_duplicate, is_kept=is_kept)
            self.items_tree.addTopLevelItem(tree_item)
            self.visible_items.add(item.bookmark_id)

        self.count_label.setText(f"{len(filtered_items)} items shown")
        self.items_tree.blockSignals(False)
        self.update_preview()

    def _passes_column_filters(self, item: DeletionItem) -> bool:
        """Check if an item passes all column filters."""
        for col_idx, filter_widget in self.filter_widgets.items():
            allowed_values = filter_widget.get_selected_values()
            if allowed_values is None:
                continue  # No filter on this column

            value = self._get_item_column_value(item, col_idx)

            if not value:
                return False

            if value not in allowed_values:
                return False
        return True

    def _get_item_column_value(self, item: DeletionItem, col_idx: int) -> str:
        """Get the display value for a column from a DeletionItem."""
        if col_idx == 1:  # Title
            return item.title
        elif col_idx == 2:  # Folder
            return item.folder_path or "Bookmarks Bar"
        elif col_idx == 3:  # URL
            return item.url
        elif col_idx == 4:  # Browser/Profile
            return f"{item.browser_name}/{item.profile_name}"
        elif col_idx == 5:  # Dead Link
            if "dead_link" in item.reason:
                return item.dead_link_detail or "Dead"
            return ""
        elif col_idx == 6:  # Duplicate
            if "exact_duplicate" in item.reason:
                return "Exact"
            elif "similar_duplicate" in item.reason:
                return "Similar"
            return ""
        elif col_idx == 100:  # Domain
            return item.url_domain or ""
        elif col_idx == 101:  # TLD
            return item.url_tld or ""
        elif col_idx == 102:  # Subdomain
            return item.url_subdomain or ""
        return ""

    def _sort_items(self, items: List[DeletionItem]) -> List[DeletionItem]:
        """Sort items by the current sort column."""
        if not items:
            return items

        def get_sort_key(item: DeletionItem):
            value = self._get_item_column_value(item, self.sort_column)
            return value.lower() if isinstance(value, str) else value

        return sorted(items, key=get_sort_key, reverse=not self.sort_ascending)

    def _update_filter_widgets(self, items: List[DeletionItem]):
        """Update filter widgets with values from current items."""
        column_values: Dict[int, Set[str]] = {col: set() for col in self.filter_widgets.keys()}

        for item in self.all_items.values():
            for col_idx in column_values.keys():
                value = self._get_item_column_value(item, col_idx)
                if value:
                    column_values[col_idx].add(value)

        for col_idx, filter_widget in self.filter_widgets.items():
            values = list(column_values.get(col_idx, []))
            filter_widget.set_values(values)

    def clear_all_filters(self):
        """Clear all column filters."""
        for filter_widget in self.filter_widgets.values():
            filter_widget.clear_filter()
        self.apply_filters()

    def on_header_clicked(self, col_idx: int):
        """Handle header click for sorting."""
        if col_idx == 0:
            return

        if self.sort_column == col_idx:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = col_idx
            self.sort_ascending = True

        headers = ["Select", "Title", "Folder", "URL", "Browser/Profile", "Dead Link", "Duplicate"]
        for i, header in enumerate(headers):
            if i == col_idx:
                indicator = " ▲" if self.sort_ascending else " ▼"
                headers[i] = header + indicator
        self.items_tree.setHeaderLabels(headers)

        self.apply_filters()

    def _create_tree_item(self, item: DeletionItem, is_duplicate: bool, is_kept: bool = False) -> QTreeWidgetItem:
        """Create a tree item for a deletion item."""
        tree_item = QTreeWidgetItem()
        tree_item.setFlags(tree_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

        if item.bookmark_id in self.selected_for_deletion:
            tree_item.setCheckState(0, Qt.CheckState.Checked)
        else:
            tree_item.setCheckState(0, Qt.CheckState.Unchecked)

        # Title
        tree_item.setText(1, item.title[:60])
        tree_item.setToolTip(1, item.title)

        # Folder
        folder_display = item.folder_path or "Bookmarks Bar"
        tree_item.setText(2, folder_display)
        tree_item.setToolTip(2, folder_display)

        # URL
        tree_item.setText(3, item.url[:80])
        tree_item.setToolTip(3, item.url)

        # Browser/Profile
        tree_item.setText(4, f"{item.browser_name}/{item.profile_name}")

        # Dead Link
        if "dead_link" in item.reason:
            dead_link_text = item.dead_link_detail or "Dead"
            tree_item.setText(5, dead_link_text)
            tree_item.setToolTip(5, dead_link_text)
            if item.dead_link_detail:
                if "404" in item.dead_link_detail:
                    tree_item.setForeground(5, QBrush(QColor(220, 53, 69)))
                elif "Timeout" in item.dead_link_detail:
                    tree_item.setForeground(5, QBrush(QColor(255, 153, 0)))
                elif "DNS" in item.dead_link_detail or "Lookup" in item.dead_link_detail:
                    tree_item.setForeground(5, QBrush(QColor(128, 0, 128)))

        # Duplicate
        if is_duplicate:
            if is_kept:
                tree_item.setText(6, "✓ KEEP")
                tree_item.setBackground(6, QBrush(QColor(200, 255, 200)))
                tree_item.setFlags(tree_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                tree_item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                if "exact_duplicate" in item.reason:
                    tree_item.setText(6, "Exact")
                    tree_item.setForeground(6, QBrush(QColor(220, 53, 69)))
                elif "similar_duplicate" in item.reason:
                    tree_item.setText(6, "Similar")
                    tree_item.setForeground(6, QBrush(QColor(255, 153, 0)))

        tree_item.setData(0, Qt.ItemDataRole.UserRole, item.bookmark_id)
        tree_item.setData(0, Qt.ItemDataRole.UserRole + 1, item.group_id)

        return tree_item

    def on_item_clicked(self, tree_item: QTreeWidgetItem, column: int):
        """Handle item clicked."""
        bookmark_id = tree_item.data(0, Qt.ItemDataRole.UserRole)
        if bookmark_id is None:
            return

        if not (tree_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return

        self.items_tree.blockSignals(True)
        if tree_item.checkState(0) == Qt.CheckState.Checked:
            tree_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.selected_for_deletion.discard(bookmark_id)
        else:
            tree_item.setCheckState(0, Qt.CheckState.Checked)
            self.selected_for_deletion.add(bookmark_id)
        self.items_tree.blockSignals(False)

        self.update_preview()

    def on_item_changed(self, tree_item: QTreeWidgetItem, column: int):
        """Handle item checkbox changed."""
        if column != 0:
            return

        bookmark_id = tree_item.data(0, Qt.ItemDataRole.UserRole)
        group_id = tree_item.data(0, Qt.ItemDataRole.UserRole + 1)

        if bookmark_id is None:
            return

        if group_id is not None and self.keep_in_group.get(group_id) == bookmark_id:
            self.items_tree.blockSignals(True)
            tree_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.items_tree.blockSignals(False)
            return

        if tree_item.checkState(0) == Qt.CheckState.Checked:
            self.selected_for_deletion.add(bookmark_id)
        else:
            self.selected_for_deletion.discard(bookmark_id)

        self.update_preview()

    def show_context_menu(self, position):
        """Show context menu for tree items."""
        item = self.items_tree.itemAt(position)
        if item is None:
            return

        bookmark_id = item.data(0, Qt.ItemDataRole.UserRole)
        group_id = item.data(0, Qt.ItemDataRole.UserRole + 1)

        if bookmark_id is None:
            return

        menu = QMenu(self)

        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            if item.checkState(0) == Qt.CheckState.Checked:
                action = menu.addAction("Uncheck (Don't Delete)")
                action.triggered.connect(lambda: self._toggle_item(item, False))
            else:
                action = menu.addAction("Check (Mark for Deletion)")
                action.triggered.connect(lambda: self._toggle_item(item, True))

        if group_id is not None:
            is_keep = self.keep_in_group.get(group_id) == bookmark_id
            if not is_keep:
                menu.addSeparator()
                keep_action = menu.addAction("✓ Set as KEEP (don't delete this one)")
                keep_action.triggered.connect(lambda: self._set_as_keep(item, bookmark_id, group_id))

        if menu.actions():
            menu.exec(self.items_tree.viewport().mapToGlobal(position))

    def _toggle_item(self, item: QTreeWidgetItem, check: bool):
        """Toggle an item's checked state."""
        bookmark_id = item.data(0, Qt.ItemDataRole.UserRole)
        if bookmark_id is None:
            return

        self.items_tree.blockSignals(True)
        if check:
            item.setCheckState(0, Qt.CheckState.Checked)
            self.selected_for_deletion.add(bookmark_id)
        else:
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.selected_for_deletion.discard(bookmark_id)
        self.items_tree.blockSignals(False)
        self.update_preview()

    def _set_as_keep(self, item: QTreeWidgetItem, bookmark_id: int, group_id: int):
        """Set this bookmark as the one to keep."""
        old_keep = self.keep_in_group.get(group_id)
        self.keep_in_group[group_id] = bookmark_id

        self.selected_for_deletion.discard(bookmark_id)

        if old_keep is not None and old_keep != bookmark_id:
            self.selected_for_deletion.add(old_keep)

        self.apply_filters()

    def select_all_visible(self):
        """Select all visible items."""
        self.items_tree.blockSignals(True)

        for bookmark_id in self.visible_items:
            item = self.all_items.get(bookmark_id)
            if not item:
                continue

            if item.group_id is not None and self.keep_in_group.get(item.group_id) == bookmark_id:
                continue

            self.selected_for_deletion.add(bookmark_id)

        for i in range(self.items_tree.topLevelItemCount()):
            tree_item = self.items_tree.topLevelItem(i)
            bookmark_id = tree_item.data(0, Qt.ItemDataRole.UserRole)
            if bookmark_id in self.selected_for_deletion:
                if tree_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    tree_item.setCheckState(0, Qt.CheckState.Checked)

        self.items_tree.blockSignals(False)
        self.update_preview()

    def deselect_all(self):
        """Deselect all items."""
        self.items_tree.blockSignals(True)
        self.selected_for_deletion.clear()

        for i in range(self.items_tree.topLevelItemCount()):
            tree_item = self.items_tree.topLevelItem(i)
            if tree_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                tree_item.setCheckState(0, Qt.CheckState.Unchecked)

        self.items_tree.blockSignals(False)
        self.update_preview()

    def deselect_visible(self):
        """Deselect only visible items."""
        self.items_tree.blockSignals(True)

        for bookmark_id in self.visible_items:
            self.selected_for_deletion.discard(bookmark_id)

        for i in range(self.items_tree.topLevelItemCount()):
            tree_item = self.items_tree.topLevelItem(i)
            if tree_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                tree_item.setCheckState(0, Qt.CheckState.Unchecked)

        self.items_tree.blockSignals(False)
        self.update_preview()

    def auto_select_duplicates(self):
        """Auto-select duplicates, keeping the first in each group."""
        self.items_tree.blockSignals(True)

        for group_id, items_list in self._get_duplicate_groups().items():
            if len(items_list) < 2:
                continue

            # Find first non-dead-link to keep
            keep_item = None
            for item in items_list:
                if "dead_link" not in item.reason:
                    keep_item = item
                    break

            if keep_item:
                self.keep_in_group[group_id] = keep_item.bookmark_id
                self.selected_for_deletion.discard(keep_item.bookmark_id)

                for item in items_list:
                    if item.bookmark_id != keep_item.bookmark_id:
                        self.selected_for_deletion.add(item.bookmark_id)
            else:
                # All are dead links - select all for deletion
                for item in items_list:
                    self.selected_for_deletion.add(item.bookmark_id)

        self.items_tree.blockSignals(False)
        self.apply_filters()

    def _get_duplicate_groups(self) -> Dict[int, List[DeletionItem]]:
        """Get all duplicate groups."""
        groups: Dict[int, List[DeletionItem]] = {}
        for item in self.all_items.values():
            if item.group_id is not None:
                if item.group_id not in groups:
                    groups[item.group_id] = []
                groups[item.group_id].append(item)
        return groups

    def update_preview(self):
        """Update the deletion preview panel with a tree view."""
        self.preview_tree.clear()

        if not self.selected_for_deletion:
            self.summary_label.setText("No items selected for deletion.\n\nTip: Use 'Auto-Select Duplicates' to quickly select all duplicates while keeping one copy of each.")
            self.delete_btn.setEnabled(False)
            self.copy_ids_btn.setEnabled(False)
            self.save_ids_btn.setEnabled(False)
            return

        self.delete_btn.setEnabled(True)
        self.copy_ids_btn.setEnabled(True)
        self.save_ids_btn.setEnabled(True)

        selected_items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]

        # Group by browser -> profile -> items
        by_browser: Dict[str, Dict[str, List[DeletionItem]]] = {}
        for item in selected_items:
            if item.browser_name not in by_browser:
                by_browser[item.browser_name] = {}
            if item.profile_name not in by_browser[item.browser_name]:
                by_browser[item.browser_name][item.profile_name] = []
            by_browser[item.browser_name][item.profile_name].append(item)

        # Build tree
        for browser_name, profiles in sorted(by_browser.items()):
            browser_count = sum(len(items) for items in profiles.values())
            browser_item = QTreeWidgetItem([f"🌐 {browser_name}", f"{browser_count} items"])
            browser_item.setExpanded(True)

            for profile_name, items in sorted(profiles.items()):
                profile_item = QTreeWidgetItem([f"👤 {profile_name}", f"{len(items)} items"])

                for item in items[:20]:  # Limit to 20 items per profile to avoid slowdown
                    title_display = item.title[:40] + "..." if len(item.title) > 40 else item.title
                    reason_parts = []
                    if "dead_link" in item.reason:
                        reason_parts.append(item.dead_link_detail or "Dead")
                    if "duplicate" in item.reason:
                        if "exact" in item.reason:
                            reason_parts.append("Exact Dup")
                        else:
                            reason_parts.append("Similar Dup")

                    bookmark_item = QTreeWidgetItem([f"📄 {title_display}", ", ".join(reason_parts)])
                    bookmark_item.setToolTip(0, f"{item.title}\n{item.url}")
                    bookmark_item.setToolTip(1, f"Folder: {item.folder_path}")
                    profile_item.addChild(bookmark_item)

                if len(items) > 20:
                    more_item = QTreeWidgetItem([f"... and {len(items) - 20} more", ""])
                    profile_item.addChild(more_item)

                profile_item.setExpanded(True)
                browser_item.addChild(profile_item)

            self.preview_tree.addTopLevelItem(browser_item)

        # Summary
        by_reason: Dict[str, int] = {}
        for item in selected_items:
            for reason in item.reason.split(","):
                reason_display = reason.replace("_", " ").title()
                by_reason[reason_display] = by_reason.get(reason_display, 0) + 1

        summary_parts = [f"Total: {len(selected_items)} bookmarks"]
        for reason, count in sorted(by_reason.items()):
            summary_parts.append(f"• {reason}: {count}")

        # Check running browsers
        running = BrowserProcessService.get_running_browsers()
        affected_browsers = {item.browser_name for item in selected_items}
        running_affected = [b for b in running if b.browser_name in affected_browsers]

        if running_affected:
            summary_parts.append("")
            summary_parts.append("⚠️ Browsers to close:")
            for b in running_affected:
                summary_parts.append(f"  • {b.browser_name}")

        self.summary_label.setText("\n".join(summary_parts))

    def show_restore_dialog(self):
        """Show dialog to restore from a backup."""
        from .restore_backup_dialog import RestoreBackupDialog
        dialog = RestoreBackupDialog(self.modifier_service.backup_dir, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self,
                "Restore Complete",
                "Bookmarks have been restored from backup.\n\n"
                "Please restart your browser(s) to see the restored bookmarks."
            )

    def start_deletion(self):
        """Start the deletion process."""
        if not self.selected_for_deletion:
            return

        selected_items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]
        affected_browsers = {item.browser_name for item in selected_items}

        running = BrowserProcessService.get_running_browsers()
        running_affected = [b for b in running if b.browser_name in affected_browsers]

        if running_affected:
            from .browser_close_dialog import BrowserCloseDialog
            dialog = BrowserCloseDialog(running_affected, self)
            result = dialog.exec()

            if result != QDialog.DialogCode.Accepted:
                return

            still_running = [
                b.browser_name for b in BrowserProcessService.get_running_browsers()
                if b.browser_name in affected_browsers
            ]

            if still_running:
                QMessageBox.warning(
                    self,
                    "Browsers Still Running",
                    f"These browsers are still running:\n\n"
                    f"{', '.join(still_running)}\n\n"
                    "Please close them before proceeding."
                )
                return

        total = len(selected_items)
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete {total} bookmark{'s' if total != 1 else ''} from your browsers?\n\n"
            "Backups will be created before any changes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.perform_deletion(selected_items)

    def perform_deletion(self, items: List[DeletionItem]):
        """Perform the actual deletion."""
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

        progress = QProgressDialog("Deleting bookmarks...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            results = self.modifier_service.delete_bookmarks(bookmarks_to_delete, create_backup=True)
            progress.close()

            success_count = sum(r.bookmarks_deleted for r in results if r.success)
            failed = [r for r in results if not r.success]
            warnings = [r for r in results if r.success and r.error_message]

            message = f"Successfully deleted {success_count} bookmarks.\n\n"
            message += "Details by profile:\n"
            for r in results:
                status = "✓" if r.success else "✗"
                message += f"  {status} {r.browser_name}/{r.profile_name}: {r.bookmarks_deleted} deleted\n"

            message += "\n"

            if failed:
                message += f"Failed to modify {len(failed)} profile(s):\n"
                for r in failed:
                    message += f"  • {r.browser_name}/{r.profile_name}: {r.error_message}\n"
                message += "\n"

            if warnings:
                message += "Warnings:\n"
                for r in warnings:
                    message += f"  • {r.browser_name}/{r.profile_name}: {r.error_message}\n"
                message += "\n"

            message += f"Backups created in:\n{self.modifier_service.backup_dir}\n\n"
            message += "⚠️ NOTE: If you have browser sync enabled, bookmarks may reappear."

            QMessageBox.information(self, "Deletion Complete", message)

            self._remove_from_database(items)
            self.load_data()

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Error during deletion:\n\n{str(e)}")

    def _remove_from_database(self, items: List[DeletionItem]):
        """Remove deleted bookmarks from our database."""
        for item in items:
            try:
                self.db.execute("DELETE FROM bookmarks WHERE bookmark_id = ?", (item.bookmark_id,))
            except Exception:
                pass
        self.db.commit()

    def _get_selected_ids_text(self) -> str:
        """Get the browser bookmark IDs for selected items as text."""
        selected_items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]
        ids = [str(item.browser_bookmark_id) for item in selected_items]
        return '\n'.join(ids)

    def _create_backups_for_selected(self) -> str:
        """Create backups of browser bookmark files for selected items."""
        selected_items = [self.all_items[bid] for bid in self.selected_for_deletion if bid in self.all_items]

        profiles_to_backup = {}
        for item in selected_items:
            key = (item.profile_path, item.browser_name, item.profile_name)
            if key not in profiles_to_backup:
                profiles_to_backup[key] = key

        backup_paths = []
        for profile_path, browser_name, profile_name in profiles_to_backup.keys():
            try:
                self.modifier_service.create_backup(
                    Path(profile_path), browser_name, profile_name
                )
                backup_paths.append(f"  • {browser_name}/{profile_name}")
            except Exception as e:
                backup_paths.append(f"  • {browser_name}/{profile_name}: FAILED - {e}")

        return "\n".join(backup_paths)

    def copy_ids_to_clipboard(self):
        """Copy selected bookmark IDs to clipboard."""
        ids_text = self._get_selected_ids_text()
        if not ids_text:
            QMessageBox.warning(self, "No Selection", "No bookmarks selected.")
            return

        backup_info = self._create_backups_for_selected()

        clipboard = QApplication.clipboard()
        clipboard.setText(ids_text)

        count = len(ids_text.strip().split('\n'))
        QMessageBox.information(
            self,
            "Copied to Clipboard",
            f"{count} bookmark ID(s) copied to clipboard.\n\n"
            f"Backups created:\n{backup_info}\n\n"
            f"Backup location:\n{self.modifier_service.backup_dir}\n\n"
            "Now open the Bookmark Manager Helper extension\n"
            "in your browser and paste the IDs there."
        )

    def save_ids_to_file(self):
        """Save selected bookmark IDs to a file."""
        from PyQt6.QtWidgets import QFileDialog

        ids_text = self._get_selected_ids_text()
        if not ids_text:
            QMessageBox.warning(self, "No Selection", "No bookmarks selected.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Bookmark IDs",
            "bookmark_ids_to_delete.txt",
            "Text Files (*.txt);;All Files (*)"
        )

        if not filename:
            return

        backup_info = self._create_backups_for_selected()

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("# Bookmark IDs to delete\n")
                f.write("# Use with Bookmark Manager Helper browser extension\n")
                f.write("# Lines starting with # are comments\n\n")
                f.write(ids_text)

            count = len(ids_text.strip().split('\n'))
            QMessageBox.information(
                self,
                "File Saved",
                f"{count} bookmark ID(s) saved to:\n{filename}\n\n"
                f"Backups created:\n{backup_info}\n\n"
                f"Backup location:\n{self.modifier_service.backup_dir}\n\n"
                "Now open the Bookmark Manager Helper extension\n"
                "in your browser and load this file."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{str(e)}")

    def show_extension_help(self):
        """Show help dialog about using the browser extension."""
        help_text = """
<h2>Browser Extension for Sync-Safe Deletion</h2>

<p><b>Why use the extension?</b></p>
<p>When you delete bookmarks by modifying the browser's bookmark file directly,
the deletions may not sync properly to your Google/Microsoft account.
This means deleted bookmarks can reappear when your browser syncs!</p>

<p>The <b>Bookmark Manager Helper</b> extension uses the official Chrome
Bookmarks API, which properly syncs deletions to your account.</p>

<h3>How to Install the Extension</h3>
<ol>
<li>Open Chrome or Edge and go to <code>chrome://extensions</code></li>
<li>Enable "Developer mode" (toggle in top right)</li>
<li>Click "Load unpacked"</li>
<li>Navigate to the browser_extension folder</li>
<li>Click "Select Folder"</li>
</ol>

<h3>How to Use</h3>
<ol>
<li>Select bookmarks to delete in this dialog</li>
<li>Click "Copy IDs to Clipboard" or "Save IDs to File..."</li>
<li>Click the extension icon in your browser toolbar</li>
<li>Paste the IDs or load the file</li>
<li>Click "Delete Bookmarks"</li>
</ol>
"""

        msg = QMessageBox(self)
        msg.setWindowTitle("Browser Extension Help")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def refresh_from_browsers(self):
        """Re-scan browser bookmark files and update the database."""
        reply = QMessageBox.question(
            self,
            "Refresh from Browsers",
            "This will re-scan all browser bookmark files and update the database:\n\n"
            "• Bookmarks deleted from browsers will be removed from the database\n"
            "• New bookmarks will be added\n"
            "• Profile names will be updated\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog("Refreshing bookmarks from browsers...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            cursor = self.db.execute("""
                SELECT browser_profile_id, browser_name, browser_profile_name, profile_path
                FROM browser_profiles
            """)
            db_profiles = {row[0]: {'browser_name': row[1], 'profile_name': row[2], 'path': row[3]}
                          for row in cursor.fetchall()}

            total_removed = 0
            profiles_updated = []

            for profile_id, profile_info in db_profiles.items():
                profile_path = Path(profile_info['path'])
                bookmarks_file = profile_path / "Bookmarks"

                if not bookmarks_file.exists():
                    continue

                progress.setLabelText(f"Scanning {profile_info['browser_name']}/{profile_info['profile_name']}...")

                browser_ids = self._get_browser_bookmark_ids(bookmarks_file)

                cursor = self.db.execute("""
                    SELECT bookmark_id, browser_bookmark_id
                    FROM bookmarks
                    WHERE browser_profile_id = ?
                """, (profile_id,))
                db_bookmarks = {str(row[1]): row[0] for row in cursor.fetchall()}

                to_remove = []
                for browser_id, bookmark_id in db_bookmarks.items():
                    if browser_id not in browser_ids:
                        to_remove.append(bookmark_id)

                for bookmark_id in to_remove:
                    self.db.execute("DELETE FROM bookmarks WHERE bookmark_id = ?", (bookmark_id,))

                if to_remove:
                    total_removed += len(to_remove)
                    profiles_updated.append(f"{profile_info['browser_name']}/{profile_info['profile_name']}: {len(to_remove)} removed")

            self.db.commit()
            progress.close()

            message = "Refresh complete!\n\n"
            if profiles_updated:
                message += "Changes:\n"
                for update in profiles_updated:
                    message += f"  • {update}\n"
            else:
                message += "No changes detected - database is in sync with browsers."

            QMessageBox.information(self, "Refresh Complete", message)

            self.load_data()

        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Error during refresh:\n\n{str(e)}")

    def _get_browser_bookmark_ids(self, bookmarks_file: Path) -> Set[str]:
        """Get all bookmark IDs from a browser bookmarks file."""
        import json

        ids = set()

        try:
            with open(bookmarks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            def extract_ids(node):
                if node.get('type') == 'url':
                    node_id = node.get('id')
                    if node_id:
                        ids.add(str(node_id))
                elif node.get('type') == 'folder':
                    for child in node.get('children', []):
                        extract_ids(child)

            roots = data.get('roots', {})
            for root_name, root_data in roots.items():
                if isinstance(root_data, dict):
                    extract_ids(root_data)

        except (json.JSONDecodeError, IOError):
            pass

        return ids
