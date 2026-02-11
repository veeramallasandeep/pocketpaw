# PocketPaw Desktop Launcher — Bootstrap Module
# Detects Python, creates venv, installs pocketpaw via pip.
# On Windows, downloads the Python embeddable package if Python is missing.
# Created: 2026-02-10

from __future__ import annotations

import io
import logging
import platform
import shutil
import subprocess
import urllib.request
import venv
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Where everything lives
POCKETCLAW_HOME = Path.home() / ".pocketclaw"
VENV_DIR = POCKETCLAW_HOME / "venv"
EMBEDDED_PYTHON_DIR = POCKETCLAW_HOME / "python"
PACKAGE_NAME = "pocketpaw"
MIN_PYTHON = (3, 11)

# Python embeddable package URL template for Windows
# Format: python-{version}-embed-{arch}.zip
PYTHON_EMBED_VERSION = "3.12.8"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/{version}/python-{version}-embed-{arch}.zip"


@dataclass
class BootstrapStatus:
    """Current state of the bootstrap environment."""

    python_path: str | None = None
    python_version: str | None = None
    venv_exists: bool = False
    pocketpaw_installed: bool = False
    pocketpaw_version: str | None = None
    needs_install: bool = True
    error: str | None = None


ProgressCallback = Callable[[str, int], None]
"""Callback(message, percent_0_to_100)."""


def _noop_progress(msg: str, pct: int) -> None:
    pass


class Bootstrap:
    """Handles Python detection, venv creation, and pocketpaw installation."""

    def __init__(self, progress: ProgressCallback | None = None) -> None:
        self.progress = progress or _noop_progress

    # ── Public API ─────────────────────────────────────────────────────

    def check_status(self) -> BootstrapStatus:
        """Check current environment status without changing anything."""
        status = BootstrapStatus()

        # Find Python
        python = self._find_python()
        if python:
            status.python_path = python
            status.python_version = self._get_python_version(python)

        # Check venv
        venv_python = self._venv_python()
        if venv_python and venv_python.exists():
            status.venv_exists = True
            # Check if pocketpaw is installed in the venv
            version = self._get_installed_version(str(venv_python))
            if version:
                status.pocketpaw_installed = True
                status.pocketpaw_version = version
                status.needs_install = False

        return status

    def run(self, extras: list[str] | None = None) -> BootstrapStatus:
        """Full bootstrap: find/install Python, create venv, install pocketpaw.

        Args:
            extras: pip extras to install (e.g. ["telegram", "discord"])

        Returns:
            BootstrapStatus with the result.
        """
        status = BootstrapStatus()
        extras = extras or ["recommended"]

        try:
            # Step 1: Find or install Python
            self.progress("Checking Python...", 5)
            python = self._find_python()

            if not python and platform.system() == "Windows":
                self.progress("Downloading Python...", 10)
                python = self._download_embedded_python()

            if not python:
                status.error = (
                    "Python 3.11+ not found. Install from https://www.python.org/downloads/"
                )
                return status

            status.python_path = python
            status.python_version = self._get_python_version(python)
            logger.info("Using Python %s at %s", status.python_version, python)

            # Step 2: Create venv if needed
            venv_python = self._venv_python()
            if not venv_python or not venv_python.exists():
                self.progress("Creating virtual environment...", 25)
                self._create_venv(python)
                venv_python = self._venv_python()
                if not venv_python or not venv_python.exists():
                    status.error = f"Failed to create venv at {VENV_DIR}"
                    return status

            status.venv_exists = True

            # Step 3: Install/upgrade pip in the venv
            self.progress("Updating pip...", 35)
            self._upgrade_pip(str(venv_python))

            # Step 4: Install pocketpaw
            self.progress("Installing PocketPaw...", 45)
            success = self._install_pocketpaw(str(venv_python), extras)
            if not success:
                status.error = "Failed to install pocketpaw. Check your internet connection."
                return status

            self.progress("Verifying installation...", 90)
            version = self._get_installed_version(str(venv_python))
            if version:
                status.pocketpaw_installed = True
                status.pocketpaw_version = version
                status.needs_install = False
            else:
                status.error = "Installation completed but pocketpaw not found in venv."

            self.progress("Ready!", 100)

        except Exception as exc:
            logger.exception("Bootstrap failed")
            status.error = str(exc)

        return status

    # ── Python Detection ───────────────────────────────────────────────

    def _find_python(self) -> str | None:
        """Find a suitable Python 3.11+ on the system."""
        # Check embedded Python first (Windows)
        embedded = self._embedded_python()
        if embedded and embedded.exists():
            if self._check_python_version(str(embedded)):
                return str(embedded)

        # Check venv Python (already created)
        venv_py = self._venv_python()
        if venv_py and venv_py.exists():
            # Venv exists but we need the base Python to recreate if needed
            pass

        # Check system Python
        candidates = ["python3", "python3.13", "python3.12", "python3.11", "python"]
        for cmd in candidates:
            path = shutil.which(cmd)
            if path and self._check_python_version(path):
                return path

        return None

    def _check_python_version(self, python: str) -> bool:
        """Check if the given Python meets minimum version."""
        try:
            result = subprocess.run(
                [python, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                major, minor = int(parts[0]), int(parts[1])
                return (major, minor) >= MIN_PYTHON
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, IndexError):
            pass
        return False

    def _get_python_version(self, python: str) -> str | None:
        """Get the full version string."""
        try:
            result = subprocess.run(
                [
                    python,
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    # ── Embedded Python (Windows) ──────────────────────────────────────

    def _embedded_python(self) -> Path | None:
        """Path to embedded Python executable."""
        if platform.system() != "Windows":
            return None
        return EMBEDDED_PYTHON_DIR / "python.exe"

    def _download_embedded_python(self) -> str | None:
        """Download Python embeddable package for Windows."""
        arch = "amd64" if platform.machine().endswith("64") else "win32"
        url = PYTHON_EMBED_URL.format(version=PYTHON_EMBED_VERSION, arch=arch)

        logger.info("Downloading Python %s from %s", PYTHON_EMBED_VERSION, url)

        try:
            EMBEDDED_PYTHON_DIR.mkdir(parents=True, exist_ok=True)

            self.progress(f"Downloading Python {PYTHON_EMBED_VERSION}...", 15)
            response = urllib.request.urlopen(url, timeout=120)
            data = response.read()

            self.progress("Extracting Python...", 20)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(EMBEDDED_PYTHON_DIR)

            # Enable pip in the embedded Python by uncommenting import site
            # in pythonXY._pth file
            pth_files = list(EMBEDDED_PYTHON_DIR.glob("python*._pth"))
            for pth_file in pth_files:
                content = pth_file.read_text()
                content = content.replace("#import site", "import site")
                pth_file.write_text(content)

            # Install pip via get-pip.py
            self.progress("Installing pip...", 22)
            get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
            get_pip_path = EMBEDDED_PYTHON_DIR / "get-pip.py"
            urllib.request.urlretrieve(get_pip_url, str(get_pip_path))

            python_exe = str(EMBEDDED_PYTHON_DIR / "python.exe")
            subprocess.run(
                [python_exe, str(get_pip_path), "--no-warn-script-location"],
                capture_output=True,
                timeout=120,
            )
            get_pip_path.unlink(missing_ok=True)

            if Path(python_exe).exists():
                logger.info("Embedded Python installed at %s", python_exe)
                return python_exe

        except Exception as exc:
            logger.error("Failed to download embedded Python: %s", exc)

        return None

    # ── Virtual Environment ────────────────────────────────────────────

    def _venv_python(self) -> Path | None:
        """Path to the Python executable inside the venv."""
        if platform.system() == "Windows":
            return VENV_DIR / "Scripts" / "python.exe"
        return VENV_DIR / "bin" / "python"

    def _create_venv(self, python: str) -> None:
        """Create a virtual environment using the given Python."""
        logger.info("Creating venv at %s using %s", VENV_DIR, python)
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)

        # Use subprocess to call the found Python's venv module
        # (more reliable than venv.create when using a different Python)
        result = subprocess.run(
            [python, "-m", "venv", str(VENV_DIR), "--clear"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            # Fallback: try venv.create if we're using the same Python
            logger.warning("subprocess venv failed, trying venv.create: %s", result.stderr)
            venv.create(str(VENV_DIR), with_pip=True, clear=True)

    def _upgrade_pip(self, venv_python: str) -> None:
        """Upgrade pip in the venv."""
        try:
            subprocess.run(
                [venv_python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Failed to upgrade pip, continuing anyway")

    # ── Package Installation ───────────────────────────────────────────

    def _install_pocketpaw(self, venv_python: str, extras: list[str]) -> bool:
        """Install pocketpaw into the venv with given extras."""
        if extras:
            pkg = f"{PACKAGE_NAME}[{','.join(extras)}]"
        else:
            pkg = PACKAGE_NAME

        logger.info("Installing %s", pkg)
        self.progress(f"Installing {pkg}...", 50)

        try:
            result = subprocess.run(
                [venv_python, "-m", "pip", "install", pkg, "--quiet"],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                logger.error("pip install failed:\n%s", result.stderr[-2000:])
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("pip install timed out after 10 minutes")
            return False
        except FileNotFoundError:
            logger.error("venv python not found: %s", venv_python)
            return False

    def _get_installed_version(self, venv_python: str) -> str | None:
        """Get the installed pocketpaw version from the venv."""
        try:
            result = subprocess.run(
                [venv_python, "-m", "pip", "show", PACKAGE_NAME],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Version:"):
                        return line.split(":", 1)[1].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
