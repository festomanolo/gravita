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
    """Return the path to Cursor's state.vscdb SQLite database."""
    return _cursor_storage_path().parent / "state.vscdb"


def _cursor_machineid_path() -> Path:
    """Return the path to the machineId file."""
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA", "")) / "Cursor" / "machineId"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "machineId"
    else:
        return Path.home() / ".config" / "cursor" / "machineid"


# ── core reset logic ──────────────────────────────────────────────────────────

def _generate_ids() -> dict:
    dev_device_id = str(uuid.uuid4())
    return {
        "telemetry.devDeviceId": dev_device_id,
        "telemetry.machineId": hashlib.sha256(os.urandom(32)).hexdigest(),
        "telemetry.macMachineId": hashlib.sha512(os.urandom(64)).hexdigest(),
        "telemetry.sqmId": "{" + str(uuid.uuid4()).upper() + "}",
        "storage.serviceMachineId": dev_device_id,
    }


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.with_suffix(f"{path.suffix}.bak.{stamp}")
    shutil.copy2(path, dest)
    return dest


def _update_storage_json(storage: Path, new_ids: dict) -> bool:
    try:
        with storage.open("r", encoding="utf-8") as f:
            config = json.load(f)
        config.update(new_ids)
        _backup(storage)
        with storage.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"[gravita] reset_machine: could not update storage.json – {e}")
        return False


def _update_sqlite(db: Path, new_ids: dict) -> bool:
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)"
        )
        for k, v in new_ids.items():
            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", (k, v)
            )
        conn.commit()
        conn.close()
        return True
