"""Gemini CLI integration: run `gemini` against the gravita API with the Gravitas skills preloaded.

Unlike agy, the Gemini CLI honors GOOGLE_GEMINI_BASE_URL, so this is the client that really uses web2api.
It runs in an isolated GEMINI_CLI_HOME so your own ~/.gemini is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from gravita.agy import VENDOR, HOME, OK, WARN, FAIL

PREFIX = HOME / "tools" / "gemini-cli"
PRIVATE_BIN = PREFIX / "node_modules" / ".bin" / "gemini"
CLI_HOME = HOME / "gemini-home"
CONF = CLI_HOME / ".gemini"
# Pinning a model keeps the CLI from running its slow auto-router before every prompt.
SETTINGS = {"security": {"auth": {"selectedType": "gemini-api-key"}}, "model": {"name": "gemini-3.6-flash"}}


def find_gemini():
    return str(PRIVATE_BIN) if PRIVATE_BIN.is_file() else shutil.which("gemini")


def install_cli():
    """npm-install the Gemini CLI into ~/.gravita/tools (no global changes). Returns (ok, message)."""
    npm = shutil.which("npm")
    if not npm:
        return False, "npm not found - install Node.js first"
    PREFIX.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([npm, "install", "--prefix", str(PREFIX), "@google/gemini-cli"],
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return (PRIVATE_BIN.is_file(), "Gemini CLI installed" if r.returncode == 0 else r.stderr.strip()[-120:])


def prepare_home():
    """(Re)build the isolated Gemini config: auth mode, Gravitas skills, Gravitas rules as context."""
    skills = CONF / "skills"
    shutil.rmtree(skills, ignore_errors=True)
    skills.mkdir(parents=True)
    for src in (VENDOR / "skills").iterdir():
        if src.is_dir():
            shutil.copytree(src, skills / src.name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(VENDOR / "rules" / "gravitas-invariants.md", CONF / "GEMINI.md")
    (CONF / "settings.json").write_text(json.dumps(SETTINGS, indent=2) + "\n")


def skills_loaded():
    skills = CONF / "skills"
    return sorted(p.name for p in skills.iterdir() if (p / "SKILL.md").is_file()) if skills.is_dir() else []


def env_for(cfg):
    env = dict(os.environ, GEMINI_CLI_HOME=str(CLI_HOME),
               GOOGLE_GEMINI_BASE_URL=f"http://127.0.0.1:{cfg['port']}")
    env["GEMINI_API_KEY"] = (cfg.get("api_keys") or ["none"])[0]
    return env


def checks(cfg):
    """Rows for the health panel: (label, status, detail, fix)."""
    path = find_gemini()
    names = skills_loaded()
    return [
        ("Gemini CLI", OK if path else FAIL, path or "not installed",
         "" if path else "press m to install"),
        ("Gravitas skills", OK if names else WARN, ", ".join(names) if names else "not preloaded yet",
         "" if names else "press m (or run `gravita gemini`)"),
    ]


def run(cfg, argv):
    """Run the Gemini CLI wired to gravita (installing/preparing what is missing). Returns its exit code."""
    path = find_gemini()
    if not path:
        print("gravita: installing the Gemini CLI (one time)...", file=sys.stderr)
        ok, text = install_cli()
        if not ok:
            print(f"gravita: {text}", file=sys.stderr)
            return 1
        path = find_gemini()
    prepare_home()
    print(f"gravita: gemini -> gravita API http://127.0.0.1:{cfg['port']}  |  "
          f"skills: {', '.join(skills_loaded())}", file=sys.stderr)
    return subprocess.call([path, *argv], env=env_for(cfg))
