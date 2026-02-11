# PocketPaw Desktop Launcher — Entry Point
# Double-click this (packaged as .exe/.app) to:
#   1. First run: show splash, bootstrap Python/venv, install pocketpaw
#   2. Every run: start server, open browser, show system tray icon
# Created: 2026-02-10

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Set up logging before imports
LOG_DIR = Path.home() / ".pocketclaw" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("pocketpaw.launcher")


def main() -> int:
    """Main entry point for the desktop launcher."""
    parser = argparse.ArgumentParser(description="PocketPaw Desktop Launcher")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the browser automatically",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Don't show the system tray icon",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override the web dashboard port",
    )
    parser.add_argument(
        "--extras",
        default="recommended",
        help="Comma-separated pip extras for first install (default: recommended)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Force reinstall (delete venv and start fresh)",
    )
    args = parser.parse_args()

    logger.info("PocketPaw Desktop Launcher starting")

    # Import our modules
    from .bootstrap import VENV_DIR, Bootstrap
    from .server import ServerManager
    from .updater import Updater

    # Reset if requested
    if args.reset:
        import shutil

        if VENV_DIR.exists():
            logger.info("Resetting: removing venv at %s", VENV_DIR)
            shutil.rmtree(VENV_DIR)

    # Check if first run (no venv / pocketpaw not installed)
    bootstrap = Bootstrap()
    status = bootstrap.check_status()

    if status.needs_install:
        logger.info("First run detected — starting bootstrap")
        success = _first_run_install(
            bootstrap,
            extras=args.extras.split(",") if args.extras else ["recommended"],
        )
        if not success:
            logger.error("Bootstrap failed")
            return 1

    # Start the server
    server = ServerManager(port=args.port)
    updater = Updater()

    if not server.start():
        logger.error("Failed to start server")
        return 1

    # Open browser
    if not args.no_browser:
        time.sleep(1.5)
        url = server.get_dashboard_url()
        logger.info("Opening browser: %s", url)
        webbrowser.open(url)

    # Show system tray (blocks until quit)
    if not args.no_tray:
        try:
            from .tray import HAS_TRAY, TrayIcon

            if HAS_TRAY:
                tray = TrayIcon(server=server, updater=updater)
                tray.run()  # Blocks
            else:
                logger.warning("Tray not available, running headless")
                _run_headless(server)
        except ImportError:
            logger.warning("pystray not installed, running headless")
            _run_headless(server)
    else:
        _run_headless(server)

    return 0


def _first_run_install(
    bootstrap: Bootstrap,
    extras: list[str],
) -> bool:
    """Run the first-time installation with a splash screen."""
    # Try to use the tkinter splash window
    try:
        from .splash import SplashWindow

        splash = SplashWindow()

        def install_fn(progress_cb):
            result = bootstrap.run(extras=extras)
            if result.error:
                raise RuntimeError(result.error)

        # Patch bootstrap to use splash's progress callback
        def run_with_splash(progress_cb):
            bootstrap.progress = progress_cb
            result = bootstrap.run(extras=extras)
            if result.error:
                raise RuntimeError(result.error)

        success = splash.run(run_with_splash)
        return success

    except Exception as exc:
        # Fallback: no GUI, just run in console
        logger.warning("Splash window failed (%s), falling back to console", exc)

        def console_progress(msg: str, pct: int) -> None:
            print(f"  [{pct:3d}%] {msg}")

        bootstrap.progress = console_progress
        result = bootstrap.run(extras=extras)
        if result.error:
            print(f"\n  Error: {result.error}\n")
            return False
        return True


def _run_headless(server: ServerManager) -> None:
    """Run without a tray icon. Block until Ctrl+C."""
    import signal

    print(f"\n  PocketPaw running at {server.get_dashboard_url()}")
    print("  Press Ctrl+C to stop.\n")

    # Handle Ctrl+C
    stop_event = threading.Event()

    def on_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    stop_event.wait()
    server.stop()


if __name__ == "__main__":
    sys.exit(main())
