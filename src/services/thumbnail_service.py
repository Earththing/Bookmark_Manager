"""Service to generate and cache thumbnail images of URLs."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QUrl
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QApplication


class ThumbnailWorker(QThread):
    """Worker thread to generate thumbnails without blocking the UI."""

    thumbnail_ready = pyqtSignal(str, QPixmap)  # url, pixmap
    thumbnail_error = pyqtSignal(str, str)  # url, error_message

    def __init__(self, url: str, cache_path: Path, width: int = 800, height: int = 600):
        super().__init__()
        self.url = url
        self.cache_path = cache_path
        self.width = width
        self.height = height

    def run(self):
        """Generate the thumbnail."""
        try:
            pixmap = self._capture_screenshot()
            if pixmap and not pixmap.isNull():
                # Save to cache
                pixmap.save(str(self.cache_path), "PNG")
                self.thumbnail_ready.emit(self.url, pixmap)
            else:
                self.thumbnail_error.emit(self.url, "Failed to capture screenshot")
        except Exception as e:
            self.thumbnail_error.emit(self.url, str(e))

    def _capture_screenshot(self) -> Optional[QPixmap]:
        """Capture a screenshot of the URL using a headless browser approach."""
        # Try using playwright if available
        try:
            return self._capture_with_playwright()
        except ImportError:
            pass

        # Fall back to a simple approach - create a placeholder
        return self._create_placeholder()

    def _capture_with_playwright(self) -> Optional[QPixmap]:
        """Capture screenshot using Playwright."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": self.width, "height": self.height})

            try:
                page.goto(self.url, timeout=30000, wait_until="networkidle")
                # Wait a bit for any final rendering
                page.wait_for_timeout(1000)

                # Take screenshot
                screenshot_bytes = page.screenshot(type="png")
                browser.close()

                # Convert to QPixmap
                image = QImage()
                image.loadFromData(screenshot_bytes)
                return QPixmap.fromImage(image)
            except Exception as e:
                browser.close()
                raise e

    def _create_placeholder(self) -> QPixmap:
        """Create a placeholder image when screenshot capture is not available."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPainter, QFont, QColor

        pixmap = QPixmap(self.width, self.height)
        pixmap.fill(QColor(240, 240, 240))

        painter = QPainter(pixmap)
        painter.setPen(QColor(100, 100, 100))

        # Draw URL domain
        from urllib.parse import urlparse
        try:
            domain = urlparse(self.url).netloc
        except Exception:
            domain = self.url[:50]

        font = QFont("Arial", 14)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                        f"Preview not available\n\n{domain}\n\n(Install playwright for thumbnails:\npip install playwright\nplaywright install chromium)")
        painter.end()

        return pixmap


class ThumbnailService(QObject):
    """Service to manage thumbnail generation and caching."""

    thumbnail_ready = pyqtSignal(str, QPixmap)  # url, pixmap
    thumbnail_error = pyqtSignal(str, str)  # url, error_message
    thumbnail_loading = pyqtSignal(str)  # url

    def __init__(self):
        super().__init__()
        # Cache directory
        self.cache_dir = Path.home() / ".bookmark_manager" / "thumbnails"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache metadata file
        self.metadata_file = self.cache_dir / "metadata.json"
        self.metadata = self._load_metadata()

        # Currently running workers
        self.workers = {}

        # Cache duration (7 days)
        self.cache_duration = timedelta(days=7)

    def _load_metadata(self) -> dict:
        """Load cache metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_metadata(self):
        """Save cache metadata."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2)
        except IOError:
            pass

    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.png"

    def _is_cache_valid(self, url: str) -> bool:
        """Check if cached thumbnail is still valid."""
        cache_path = self._get_cache_path(url)
        if not cache_path.exists():
            return False

        # Check metadata for timestamp
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in self.metadata:
            cached_time = datetime.fromisoformat(self.metadata[url_hash].get('timestamp', ''))
            if datetime.now() - cached_time < self.cache_duration:
                return True

        return False

    def get_thumbnail(self, url: str, force_refresh: bool = False) -> Optional[QPixmap]:
        """Get a thumbnail for the URL.

        Returns cached thumbnail immediately if available,
        otherwise starts async generation and returns None.

        Args:
            url: The URL to get thumbnail for
            force_refresh: If True, ignore cache and regenerate

        Returns:
            QPixmap if cached, None if generation started
        """
        cache_path = self._get_cache_path(url)

        # Check cache first
        if not force_refresh and self._is_cache_valid(url):
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                return pixmap

        # Check if already generating
        if url in self.workers:
            return None

        # Start async generation
        self.thumbnail_loading.emit(url)
        self._start_worker(url, cache_path)
        return None

    def _start_worker(self, url: str, cache_path: Path):
        """Start a worker thread to generate thumbnail."""
        worker = ThumbnailWorker(url, cache_path)
        worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        worker.thumbnail_error.connect(self._on_thumbnail_error)
        worker.finished.connect(lambda: self._cleanup_worker(url))

        self.workers[url] = worker
        worker.start()

    def _on_thumbnail_ready(self, url: str, pixmap: QPixmap):
        """Handle thumbnail generation complete."""
        # Update metadata
        url_hash = hashlib.md5(url.encode()).hexdigest()
        self.metadata[url_hash] = {
            'url': url,
            'timestamp': datetime.now().isoformat()
        }
        self._save_metadata()

        # Emit signal
        self.thumbnail_ready.emit(url, pixmap)

    def _on_thumbnail_error(self, url: str, error: str):
        """Handle thumbnail generation error."""
        self.thumbnail_error.emit(url, error)

    def _cleanup_worker(self, url: str):
        """Clean up finished worker."""
        if url in self.workers:
            worker = self.workers.pop(url)
            worker.deleteLater()

    def clear_cache(self):
        """Clear all cached thumbnails."""
        for file in self.cache_dir.glob("*.png"):
            try:
                file.unlink()
            except IOError:
                pass
        self.metadata = {}
        self._save_metadata()

    def get_cache_size(self) -> Tuple[int, int]:
        """Get cache statistics.

        Returns:
            Tuple of (file_count, total_size_bytes)
        """
        files = list(self.cache_dir.glob("*.png"))
        total_size = sum(f.stat().st_size for f in files)
        return len(files), total_size


# Global instance
_thumbnail_service = None


def get_thumbnail_service() -> ThumbnailService:
    """Get the global thumbnail service instance."""
    global _thumbnail_service
    if _thumbnail_service is None:
        _thumbnail_service = ThumbnailService()
    return _thumbnail_service
