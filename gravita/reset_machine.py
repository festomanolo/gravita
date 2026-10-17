"""
reset_machine.py – Reset Windsurf IDE machine/telemetry IDs before gravita starts.

Windsurf stores its identity in three places:
  • ~/Library/Application Support/Windsurf/User/globalStorage/storage.json
      keys: telemetry.machineId, telemetry.devDeviceId, telemetry.sqmId
  • ~/Library/Application Support/Windsurf/User/globalStorage/state.vscdb
      ItemTable keys: storage.serviceMachineId
  • ~/Library/Application Support/Windsurf/machineid
      plain-text UUID

This module is stdlib-only (no third-party deps).
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


# ── path resolution ───────────────────────────────────────────────────────────

def _windsurf_base() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Windsurf"
    elif sys.platform.startswith("linux"):
        sudo_user = os.environ.get("SUDO_USER")
        home = Path(f"/home/{sudo_user}") if sudo_user else Path.home()
        return home / ".config" / "Windsurf"
    elif sys.platform == "win32":
        return Path(os.getenv("APPDATA", "")) / "Windsurf"
    else:
        raise OSError(f"Unsupported OS: {sys.platform}")


def _storage_json() -> Path:
    return _windsurf_base() / "User" / "globalStorage" / "storage.json"


def _state_db() -> Path:
    return _windsurf_base() / "User" / "globalStorage" / "state.vscdb"


def _machineid_file() -> Path:
    return _windsurf_base() / "machineid"


# ── ID generation ─────────────────────────────────────────────────────────────

def _generate_ids() -> dict:
    dev_device_id = str(uuid.uuid4())
    machine_id = hashlib.sha256(os.urandom(32)).hexdigest()
    sqm_id = "{" + str(uuid.uuid4()).upper() + "}"
    service_machine_id = str(uuid.uuid4())
    return {
        # storage.json keys
        "telemetry.devDeviceId": dev_device_id,
        "telemetry.machineId": machine_id,
        "telemetry.sqmId": sqm_id,
        # SQLite keys
        "storage.serviceMachineId": service_machine_id,
        # machineid file (use service_machine_id to stay consistent)
        "_machineid": service_machine_id,
    }


# ── writers ───────────────────────────────────────────────────────────────────

def _backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.with_suffix(f"{path.suffix}.bak.{stamp}")
    shutil.copy2(path, dest)


def _update_storage_json(path: Path, new_ids: dict) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _backup(path)
        for key in ("telemetry.devDeviceId", "telemetry.machineId", "telemetry.sqmId"):
            data[key] = new_ids[key]
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[gravita] reset_machine: storage.json update failed – {e}")
        return False


def _update_sqlite(path: Path, new_ids: dict) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            ("storage.serviceMachineId", new_ids["storage.serviceMachineId"]),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[gravita] reset_machine: state.vscdb update failed – {e}")
        return False


def _update_machineid(path: Path, new_id: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            _backup(path)
        path.write_text(new_id, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[gravita] reset_machine: machineid update failed – {e}")
        return False


# ── public entry point ────────────────────────────────────────────────────────

def reset_windsurf_machine_id(verbose: bool = True) -> bool:
    """
    Rotate all Windsurf machine/telemetry IDs.

    Returns True if storage.json was updated, False if Windsurf data is not
    found or writes fail. Always safe to call – skips silently when Windsurf
    is not installed.
    """
    storage = _storage_json()

    if not storage.exists():
        if verbose:
            print(
                f"[gravita] reset_machine: Windsurf storage.json not found "
                f"({storage}) – skipping."
            )
        return False

    if verbose:
        print("[gravita] Rotating Windsurf machine IDs …")

    ids = _generate_ids()

    ok_json   = _update_storage_json(storage, ids)
    ok_sqlite = _update_sqlite(_state_db(), ids) if _state_db().exists() else True
    ok_mid    = _update_machineid(_machineid_file(), ids["_machineid"])

    if verbose:
        if ok_json and ok_sqlite and ok_mid:
            print("[gravita] Windsurf machine IDs rotated successfully.")
        else:
            print("[gravita] Windsurf machine ID rotation completed with some errors (see above).")

    return ok_json


# keep the old name as an alias so nothing else breaks
reset_cursor_machine_id = reset_windsurf_machine_id
