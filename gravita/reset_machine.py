"""
reset_machine.py – Reset Cursor IDE machine/telemetry IDs before gravita starts.

Ported from cursor-free-vip/reset_machine_manual.py (MIT licence).
All external dependencies (colorama, translator, config, new_signup) have been
removed so this module runs with the standard library only.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _cursor_storage_path() -> Path:
    """Return the path to Cursor's storage.json for the current OS."""
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA", "")
        return Path(appdata) / "Cursor" / "User" / "globalStorage" / "storage.json"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "storage.json"
    elif sys.platform.startswith("linux"):
        sudo_user = os.environ.get("SUDO_USER")
        home = Path(f"/home/{sudo_user}") if sudo_user else Path.home()
        return home / ".config" / "cursor" / "User" / "globalStorage" / "storage.json"
    else:
        raise OSError(f"Unsupported OS: {sys.platform}")


def _cursor_sqlite_path() -> Path:
