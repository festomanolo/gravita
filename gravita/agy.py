"""Antigravity CLI (agy) integration: install Gravitas, check health, launch agy through gravita."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = "gravitas-native"
VENDOR = Path(__file__).resolve().parent / "vendor" / "gravitas-antigravity"
HOME = Path.home() / ".gravita"
INSTALLED = HOME / "plugins" / "gravitas-antigravity"

OK, WARN, FAIL = "ok", "warn", "fail"


def find_agy():
    return shutil.which("agy") or next(
        (str(p) for p in (Path.home() / ".local" / "bin" / "agy",) if p.is_file()), None)


def _run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def plugin_state(agy):
    """Return 'enabled', 'disabled', or 'missing' for the Gravitas plugin."""
    code, out = _run([agy, "plugin", "list", "--json"])
    if code != 0:
        return "missing"
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    rows = data if isinstance(data, list) else (data or {}).get("plugins", []) if isinstance(data, dict) else []
    for row in rows:
        if isinstance(row, dict) and row.get("name") == PLUGIN:
            return "disabled" if row.get("enabled") is False else "enabled"
    return "missing"


def install(agy):
    """Copy the bundled plugin to a stable path and (re)install it. Returns (ok, message)."""
    if not VENDOR.is_dir():
        return False, "bundled Gravitas plugin not found in this install"
    INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(INSTALLED, ignore_errors=True)
    shutil.copytree(VENDOR, INSTALLED, ignore=shutil.ignore_patterns("__pycache__"))
    if plugin_state(agy) != "missing":
        _run([agy, "plugin", "uninstall", PLUGIN])
    code, out = _run([agy, "plugin", "install", str(INSTALLED)], timeout=60)
    if code != 0:
        return False, out.splitlines()[-1] if out else "agy plugin install failed"
    if plugin_state(agy) == "disabled":
        _run([agy, "plugin", "enable", PLUGIN])
    state = plugin_state(agy)
    return state == "enabled", f"Gravitas plugin {state}"


def routing(cfg):
    """Where would an agy launched from THIS shell send its requests?"""
    key, base = os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GOOGLE_GEMINI_BASE_URL", "")
    port = str(cfg.get("port"))
    if key in (cfg.get("api_keys") or []) and key and port in base:
        return OK, "gravita API (via env in this shell)"
    if key or base:
        return WARN, "a different API key/URL is set in this shell"
    return WARN, "agy's own signed-in account (not gravita)"


def checks(cfg, engine_ready):
    """Health checklist: list of (label, status, detail, fix_hint)."""
    out = [("Engine", OK if engine_ready else FAIL,
            "serving on :%s" % cfg["port"] if engine_ready else "not responding",
            "" if engine_ready else "press s to start, r to restart")]
    agy = find_agy()
    out.append(("agy CLI", OK if agy else FAIL, agy or "not found",
                "" if agy else "install Antigravity CLI first"))
    py = shutil.which("python3")
    out.append(("python3 for hooks", OK if py else FAIL, py or "not on PATH",
                "" if py else "Gravitas hooks run `python3`"))
    state = plugin_state(agy) if agy else "missing"
    detail = {"enabled": "auto-loads on every agy session", "disabled": "installed but disabled",
              "missing": "not installed"}[state]
    out.append(("Gravitas plugin", OK if state == "enabled" else FAIL, detail,
                "" if state == "enabled" else "press i to install"))
    status, detail = routing(cfg)
    out.append(("agy backend", status, detail,
                "" if status == OK else "run `gravita agy` to launch through gravita"))
    out.append(("Pro cookie", OK if cfg.get("cookie_file") else WARN,
                "set" if cfg.get("cookie_file") else "optional: needed for real gemini-3.1-pro",
                "" if cfg.get("cookie_file") else "press c to add"))
    return out


def launch(cfg, argv):
    """Exec agy with gravita's endpoint exported, after saying so out loud."""
    agy = find_agy()
    if not agy:
        sys.exit("gravita: agy not found")
    key = (cfg.get("api_keys") or [""])[0]
    env = dict(os.environ, GOOGLE_GEMINI_BASE_URL=f"http://127.0.0.1:{cfg['port']}")
    if key:
        env["GEMINI_API_KEY"] = key
    print(f"gravita: launching agy -> gravita API http://127.0.0.1:{cfg['port']}/v1 "
          f"(Gravitas plugin: {plugin_state(agy)})", file=sys.stderr)
    os.execve(agy, [agy, *argv], env)
