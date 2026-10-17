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
