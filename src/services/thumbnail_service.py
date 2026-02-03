"""Service to generate and cache thumbnail images of URLs."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, List, Callable
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QUrl
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QApplication


def check_playwright_available() -> bool:
    """Check if Playwright is installed and configured."""
    try:
        from playwright.sync_api import sync_playwright
        # Try to actually launch - this will fail if browsers aren't installed
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def capture_screenshot_sync(url: str, cache_path: Path, width: int = 800, height: int = 600) -> Tuple[bool, str]:
    """Capture screenshot synchronously (for use in thread pool).

    Returns:
        Tuple of (success, error_message_or_empty)
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})

            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(1000)

                # Take screenshot directly to file
                page.screenshot(path=str(cache_path), type="png")
                browser.close()
                return True, ""
            except Exception as e:
                browser.close()
                return False, str(e)
    except ImportError:
        return False, "Playwright not installed"
    except Exception as e:
        return False, str(e)


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


class BatchThumbnailWorker(QThread):
    """Worker thread for batch thumbnail generation with thread pool."""

    # Signals
    progress = pyqtSignal(int, int, str)  # current, total, current_url
    thumbnail_generated = pyqtSignal(str, bool, str)  # url, success, error_message
    finished_batch = pyqtSignal(int, int)  # success_count, error_count

    def __init__(self, urls: List[str], cache_dir: Path, max_workers: int = 4,
                 skip_cached: bool = True, metadata: dict = None):
        super().__init__()
        self.urls = urls
        self.cache_dir = cache_dir
        self.max_workers = max_workers
        self.skip_cached = skip_cached
        self.metadata = metadata or {}
        self.cache_duration = timedelta(days=7)
        self._cancelled = False

    def cancel(self):
        """Cancel the batch operation."""
        self._cancelled = True

    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.png"

    def _is_cache_valid(self, url: str) -> bool:
        """Check if cached thumbnail is still valid."""
        cache_path = self._get_cache_path(url)
        if not cache_path.exists():
            return False

        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in self.metadata:
            try:
                cached_time = datetime.fromisoformat(self.metadata[url_hash].get('timestamp', ''))
                if datetime.now() - cached_time < self.cache_duration:
                    return True
            except (ValueError, KeyError):
                pass
        return False

    def run(self):
        """Run batch thumbnail generation."""
        # Filter URLs if skipping cached
        urls_to_process = []
        for url in self.urls:
            if self._cancelled:
                break
            if self.skip_cached and self._is_cache_valid(url):
                self.thumbnail_generated.emit(url, True, "cached")
            else:
                urls_to_process.append(url)

        if not urls_to_process or self._cancelled:
            self.finished_batch.emit(len(self.urls) - len(urls_to_process), 0)
            return

        success_count = len(self.urls) - len(urls_to_process)  # Count cached as success
        error_count = 0

        # Process in batches using thread pool
        # Note: Playwright has issues with concurrent instances, so we use max_workers=2
        effective_workers = min(self.max_workers, 2)  # Limit for Playwright stability

        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            # Submit all tasks
            future_to_url = {}
            for url in urls_to_process:
                if self._cancelled:
                    break
                cache_path = self._get_cache_path(url)
                future = executor.submit(capture_screenshot_sync, url, cache_path)
                future_to_url[future] = url

            # Process completed tasks
            completed = 0
            total = len(urls_to_process)

            for future in as_completed(future_to_url):
                if self._cancelled:
                    # Cancel remaining futures
                    for f in future_to_url:
                        f.cancel()
                    break

                url = future_to_url[future]
                completed += 1

                try:
                    success, error = future.result()
                    if success:
                        success_count += 1
                        self.thumbnail_generated.emit(url, True, "")
                    else:
                        error_count += 1
                        self.thumbnail_generated.emit(url, False, error)
                except Exception as e:
                    error_count += 1
                    self.thumbnail_generated.emit(url, False, str(e))

                self.progress.emit(completed, total, url)

        self.finished_batch.emit(success_count, error_count)


class ThumbnailService(QObject):
    """Service to manage thumbnail generation and caching."""

    thumbnail_ready = pyqtSignal(str, QPixmap)  # url, pixmap
    thumbnail_error = pyqtSignal(str, str)  # url, error_message
    thumbnail_loading = pyqtSignal(str)  # url

    # Batch signals
    batch_progress = pyqtSignal(int, int, str)  # current, total, url
    batch_thumbnail_generated = pyqtSignal(str, bool, str)  # url, success, error
    batch_finished = pyqtSignal(int, int)  # success_count, error_count

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

        # Batch worker
        self.batch_worker: Optional[BatchThumbnailWorker] = None

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
            try:
                cached_time = datetime.fromisoformat(self.metadata[url_hash].get('timestamp', ''))
                if datetime.now() - cached_time < self.cache_duration:
                    return True
            except (ValueError, KeyError):
                pass

        return False

    def has_cached_thumbnail(self, url: str) -> bool:
        """Check if a valid cached thumbnail exists for the URL."""
        return self._is_cache_valid(url)

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

    def get_cached_thumbnail(self, url: str) -> Optional[QPixmap]:
        """Get a cached thumbnail without triggering generation.

        Returns:
            QPixmap if cached, None if not cached
        """
        if self._is_cache_valid(url):
            cache_path = self._get_cache_path(url)
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                return pixmap
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

    def generate_batch(self, urls: List[str], max_workers: int = 2,
                       skip_cached: bool = True) -> bool:
        """Start batch thumbnail generation.

        Args:
            urls: List of URLs to generate thumbnails for
            max_workers: Number of concurrent workers (limited to 2 for Playwright stability)
            skip_cached: If True, skip URLs that already have valid cached thumbnails

        Returns:
            True if batch started, False if another batch is running
        """
        if self.batch_worker and self.batch_worker.isRunning():
            return False

        self.batch_worker = BatchThumbnailWorker(
            urls=urls,
            cache_dir=self.cache_dir,
            max_workers=max_workers,
            skip_cached=skip_cached,
            metadata=self.metadata
        )

        # Connect signals
        self.batch_worker.progress.connect(self._on_batch_progress)
        self.batch_worker.thumbnail_generated.connect(self._on_batch_thumbnail)
        self.batch_worker.finished_batch.connect(self._on_batch_finished)

        self.batch_worker.start()
        return True

    def cancel_batch(self):
        """Cancel the running batch operation."""
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()

    def is_batch_running(self) -> bool:
        """Check if a batch operation is running."""
        return self.batch_worker is not None and self.batch_worker.isRunning()

    def _on_batch_progress(self, current: int, total: int, url: str):
        """Handle batch progress update."""
        self.batch_progress.emit(current, total, url)

    def _on_batch_thumbnail(self, url: str, success: bool, error: str):
        """Handle individual thumbnail in batch."""
        if success and error != "cached":
            # Update metadata for newly generated thumbnails
            url_hash = hashlib.md5(url.encode()).hexdigest()
            self.metadata[url_hash] = {
                'url': url,
                'timestamp': datetime.now().isoformat()
            }
        self.batch_thumbnail_generated.emit(url, success, error)

    def _on_batch_finished(self, success_count: int, error_count: int):
        """Handle batch completion."""
        self._save_metadata()
        self.batch_finished.emit(success_count, error_count)

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
