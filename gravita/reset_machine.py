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
