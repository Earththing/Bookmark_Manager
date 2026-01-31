"""GUI entry point for the Bookmark Manager application."""

import sys
from PyQt6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main():
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Bookmark Manager")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
