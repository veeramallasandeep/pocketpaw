# PocketPaw Desktop Launcher

A lightweight desktop app (~15MB) that lets non-developers run PocketPaw with zero terminal usage. Download, double-click, done.

## What it does

1. **First run** — Detects Python 3.11+ on your system (or downloads it on Windows), creates a virtual environment, and installs PocketPaw via pip. A progress window shows each step.
2. **Every run** — Starts the PocketPaw server on localhost, opens your browser to the dashboard, and sits in your system tray for quick access.

```
┌─────────────────────────────────┐
│  Double-click PocketPaw.app     │
│          ↓                      │
│  Python 3.11+ found?            │
│    yes → create venv            │
│    no  → download (Windows)     │
│          ↓                      │
│  pip install pocketpaw          │
│          ↓                      │
│  Start server → open browser    │
│          ↓                      │
│  System tray icon 🐾            │
│  (Start/Stop/Update/Quit)       │
└─────────────────────────────────┘
```

## Modules

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point — orchestrates bootstrap, server, tray |
| `bootstrap.py` | Python detection, venv creation, pip install |
| `server.py` | Server process lifecycle, PID management, health checks |
| `tray.py` | System tray icon with dynamic menu (via pystray) |
| `splash.py` | First-run tkinter progress window |
| `updater.py` | PyPI version check and one-click upgrade |
| `build/build.py` | PyInstaller build script |
| `build/launcher.spec` | PyInstaller spec file (folder mode, platform-specific) |

## Running from source

No build needed to test the launcher locally:

```bash
# From the repo root
cd /path/to/pocketpaw

# Run the launcher module directly
PYTHONPATH=. python -m installer.launcher

# With options
PYTHONPATH=. python -m installer.launcher --no-browser --no-tray --port 9999
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--no-browser` | Don't auto-open the browser |
| `--no-tray` | Run headless (no system tray icon, Ctrl+C to stop) |
| `--port PORT` | Override the dashboard port (default: 8888) |
| `--extras LIST` | Comma-separated pip extras, e.g. `telegram,discord` (default: `recommended`) |
| `--reset` | Delete the venv and reinstall from scratch |

## Building

### Prerequisites

```bash
pip install pyinstaller pystray Pillow
```

### Build for your platform

```bash
python installer/launcher/build/build.py
```

Output goes to `dist/launcher/`.

### macOS — create .dmg

```bash
# After build.py finishes:
hdiutil create -volname PocketPaw \
  -srcfolder dist/launcher/PocketPaw.app \
  -ov -format UDZO \
  dist/launcher/PocketPaw.dmg
```

### Windows — create installer

Option A: Use [Inno Setup](https://jrsoftware.org/isinfo.php) (free) — point it at `dist\launcher\PocketPaw\`.

Option B: Zip the folder for a portable build:
```powershell
Compress-Archive -Path dist\launcher\PocketPaw -DestinationPath dist\launcher\PocketPaw-portable.zip
```

### Automated builds (CI)

The GitHub Actions workflow `.github/workflows/build-launcher.yml` builds for:
- **macOS (Apple Silicon)** — `.dmg`
- **macOS (Intel)** — `.dmg`
- **Windows** — `.exe` installer (via Inno Setup)

Triggered on:
- **Release published** — artifacts are attached to the GitHub release
- **Manual dispatch** — artifacts are uploaded as workflow artifacts

## How it works

### Bootstrap (`bootstrap.py`)

1. Searches for Python 3.11+ in common locations (`python3`, `python3.12`, `python3.11`, etc.)
2. On Windows, if no Python found, downloads the [Python embeddable package](https://www.python.org/downloads/) (~15MB, no admin needed)
3. Creates a venv at `~/.pocketclaw/venv/`
4. Runs `pip install pocketpaw[recommended]` inside the venv

### Server management (`server.py`)

- Starts PocketPaw as a subprocess: `{venv}/bin/python -m pocketclaw --port {port}`
- Writes PID to `~/.pocketclaw/launcher.pid`
- Health check via HTTP GET to `http://127.0.0.1:{port}/`
- Graceful shutdown: SIGTERM → wait → SIGKILL
- Auto-finds a free port if the default (8888) is occupied

### System tray (`tray.py`)

- Cross-platform via [pystray](https://github.com/moses-palmer/pystray)
- Menu: Open Dashboard, Start/Stop Server, Restart, Check for Updates, Quit
- Checks PyPI for updates every 6 hours
- Shows desktop notifications for available updates

### Updates (`updater.py`)

- Fetches `https://pypi.org/pypi/pocketpaw/json` for the latest version
- Compares with the installed version in the venv
- Applies via `pip install --upgrade pocketpaw`

## File locations

| Path | Purpose |
|------|---------|
| `~/.pocketclaw/venv/` | Virtual environment with pocketpaw installed |
| `~/.pocketclaw/config.json` | PocketPaw configuration |
| `~/.pocketclaw/launcher.pid` | Server process PID |
| `~/.pocketclaw/logs/launcher.log` | Launcher log file |
| `~/.pocketclaw/python/` | Embedded Python (Windows only) |

## Tests

53 unit tests covering bootstrap, server, and updater:

```bash
PYTHONPATH=. uv run pytest tests/test_launcher_bootstrap.py tests/test_launcher_server.py tests/test_launcher_updater.py -v
```

## Architecture decisions

**Why a thin launcher instead of bundling everything?**
PocketPaw with all dependencies is 150-300MB. The launcher itself is ~15MB. By keeping pocketpaw in a pip-managed venv, users get standard `pip install --upgrade` updates instead of downloading a new 300MB app every time.

**Why PyInstaller folder mode?**
One-file mode extracts to a temp dir on every launch (slow startup). Folder mode starts instantly and is easier to debug.

**Why tkinter for the splash?**
It's built into Python — no extra dependency. The splash only appears once (first install), so it doesn't need to be fancy.
