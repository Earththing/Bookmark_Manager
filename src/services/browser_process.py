"""Service to detect and manage browser processes."""

import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
import psutil


@dataclass
class BrowserProcess:
    """Information about a running browser process."""
    browser_name: str  # "Chrome" or "Edge"
    process_name: str  # "chrome.exe" or "msedge.exe"
    pid: int
    is_running: bool


class BrowserProcessService:
    """Service to detect and manage browser processes."""

    # Map browser names to their process names
    BROWSER_PROCESSES = {
        "Chrome": "chrome.exe",
        "Edge": "msedge.exe",
    }

    @classmethod
    def get_running_browsers(cls) -> List[BrowserProcess]:
        """Get list of currently running browsers.

        Returns:
            List of BrowserProcess for each running browser type
        """
        running = []

        for browser_name, process_name in cls.BROWSER_PROCESSES.items():
            pids = cls._get_process_pids(process_name)
            if pids:
                # Just report the main process (lowest PID is usually the main one)
                running.append(BrowserProcess(
                    browser_name=browser_name,
                    process_name=process_name,
                    pid=min(pids),
                    is_running=True
                ))

        return running

    @classmethod
    def is_browser_running(cls, browser_name: str) -> bool:
        """Check if a specific browser is running.

        Args:
            browser_name: "Chrome" or "Edge"

        Returns:
            True if the browser is running
        """
        process_name = cls.BROWSER_PROCESSES.get(browser_name)
        if not process_name:
            return False

        return len(cls._get_process_pids(process_name)) > 0

    @classmethod
    def _get_process_pids(cls, process_name: str) -> List[int]:
        """Get all PIDs for a process name.

        Args:
            process_name: The process executable name

        Returns:
            List of PIDs
        """
        pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                    pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids

    @classmethod
    def close_browser(cls, browser_name: str, force: bool = False, timeout: int = 10) -> Tuple[bool, str]:
        """Attempt to close a browser.

        Args:
            browser_name: "Chrome" or "Edge"
            force: If True, forcefully terminate the process
            timeout: Seconds to wait for graceful close

        Returns:
            Tuple of (success, message)
        """
        process_name = cls.BROWSER_PROCESSES.get(browser_name)
        if not process_name:
            return False, f"Unknown browser: {browser_name}"

        pids = cls._get_process_pids(process_name)
        if not pids:
            return True, f"{browser_name} is not running"

        try:
            if force:
                # Force kill all processes
                for pid in pids:
                    try:
                        proc = psutil.Process(pid)
                        proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Wait briefly for processes to terminate
                time.sleep(1)

                # Check if closed
                if not cls.is_browser_running(browser_name):
                    return True, f"{browser_name} was forcefully closed"
                else:
                    return False, f"Failed to force close {browser_name}"
            else:
                # Try graceful close using taskkill
                result = subprocess.run(
                    ['taskkill', '/IM', process_name],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

                # Wait for browser to close
                for _ in range(timeout):
                    time.sleep(1)
                    if not cls.is_browser_running(browser_name):
                        return True, f"{browser_name} closed successfully"

                return False, f"{browser_name} did not close within {timeout} seconds"

        except subprocess.TimeoutExpired:
            return False, f"Timeout waiting for {browser_name} to close"
        except Exception as e:
            return False, f"Error closing {browser_name}: {str(e)}"

    @classmethod
    def wait_for_browser_close(cls, browser_name: str, timeout: int = 30) -> Tuple[bool, str]:
        """Wait for a browser to close (user closes it manually).

        Args:
            browser_name: "Chrome" or "Edge"
            timeout: Maximum seconds to wait

        Returns:
            Tuple of (closed, message)
        """
        for i in range(timeout):
            if not cls.is_browser_running(browser_name):
                return True, f"{browser_name} is now closed"
            time.sleep(1)

        return False, f"{browser_name} is still running after {timeout} seconds"
