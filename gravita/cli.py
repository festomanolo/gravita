"""gravita terminal UI: start, watch and talk to the local Gemini-to-OpenAI engine."""
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from gravita import __version__

try:
    import curses
except ImportError:  # Windows has no curses
    sys.exit("gravita needs a POSIX terminal (macOS or Linux).")

ENGINE = Path(__file__).resolve().parent / "engine" / "gemini_web2api.py"
HOME = Path.home() / ".gravita"
CONF = HOME / "config.json"
LOG = HOME / "engine.log"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never proxy localhost
DEFAULTS = {
    "port": 8081, "host": "127.0.0.1", "retry_attempts": 3, "retry_delay_sec": 2,
    "request_timeout_sec": 180, "default_model": "gemini-3.6-flash",
    "gemini_bl": "boq_assistant-bard-web-server_20260716.08_p0", "auth_user": None,
    "xsrf_token": None, "api_keys": [], "cookie_file": None, "proxy": None,
    "log_requests": False, "temporary_chats": False,
}


def load():
    try:
        return {**DEFAULTS, **json.loads(CONF.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(cfg):
    CONF.write_text(json.dumps(cfg, indent=2) + "\n")


def auth(cfg):
    keys = cfg.get("api_keys") or []
    return {"Authorization": f"Bearer {keys[0]}"} if keys else {}


def bootstrap():
    HOME.mkdir(exist_ok=True)
    if not CONF.exists():
        save(dict(DEFAULTS, api_keys=["sk-gravita-" + secrets.token_hex(16)]))


class Engine:
    def __init__(self):
        self.p = None
        self.cfg = {}
        self.started = 0.0
        self.ready = False
        self.test = ""
        threading.Thread(target=self._poll, daemon=True).start()

    def running(self):
        return self.p is not None and self.p.poll() is None

    def start(self):
        if self.running():
            return
        self.cfg = load()
        with open(LOG, "ab") as log:
            log.write(f"\n--- start {time.strftime('%H:%M:%S')} ---\n".encode())
            self.p = subprocess.Popen(
                [sys.executable, "-u", str(ENGINE), "--config", str(CONF)],
                stdout=log, stderr=subprocess.STDOUT, cwd=str(HOME),
            )
        self.started = time.time()

    def stop(self):
        if self.running():
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self.p = None
        self.ready = False

    def _poll(self):
        while True:
            ok = False
            if self.running():
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{self.cfg['port']}/v1/models", headers=auth(self.cfg))
                    with OPENER.open(req, timeout=2) as r:
                        ok = r.status == 200
                except Exception:
                    ok = False
            self.ready = ok
            time.sleep(1)

    def run_test(self):
        def work():
            cfg = self.cfg or load()
            body = json.dumps({"model": "gemini-flash-lite",
                               "messages": [{"role": "user", "content": "Reply: ok"}]}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{cfg['port']}/v1/chat/completions", data=body, method="POST",
                headers={"Content-Type": "application/json", **auth(cfg)})
            try:
                with OPENER.open(req, timeout=120) as r:
                    text = json.load(r)["choices"][0]["message"]["content"] or ""
                self.test = "test ok: " + text.strip()[:70]
            except Exception as e:
                self.test = f"test failed: {e}"[:120]
        self.test = "testing..."
        threading.Thread(target=work, daemon=True).start()


def tail(n):
    try:
        with open(LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 16384))
            return f.read().decode(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def prompt(scr, label):
    h, w = scr.getmaxyx()
    scr.timeout(-1)
    curses.echo()
    curses.curs_set(1)
    scr.move(h - 2, 0)
    scr.clrtoeol()
    scr.addnstr(h - 2, 0, label, w - 1)
    try:
        return scr.getstr(h - 2, len(label), 300).decode(errors="ignore").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
        scr.timeout(400)


def ui(scr, eng):
    curses.curs_set(0)
    scr.timeout(400)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
    reveal, msg = False, "engine starting"
    eng.start()

    def put(y, x, text, attr=0):
        try:
            scr.addnstr(y, x, text, max(0, scr.getmaxyx()[1] - x - 1), attr)
        except curses.error:
            pass

    while True:
        cfg = load()
        h, w = scr.getmaxyx()
        scr.erase()
        if eng.running():
            state, color = ("ready", 1) if eng.ready else ("starting", 2)
            state += f"  pid {eng.p.pid}  up {int(time.time() - eng.started)}s"
        elif eng.p is not None:
            state, color = f"exited ({eng.p.returncode}) - see log", 3
        else:
            state, color = "stopped", 3
        port = cfg["port"]
        key = cfg["api_keys"][0] if cfg["api_keys"] else "(none - open access)"
        shown = key if reveal or not cfg["api_keys"] else key[:12] + "..."
        put(0, 1, f"gravita {__version__}", curses.A_BOLD)
        put(0, 18, "● " + state, curses.color_pair(color) | curses.A_BOLD)
        put(2, 2, f"Base URL  http://127.0.0.1:{port}/v1")
        put(3, 2, f"API key   {shown}")
        put(4, 2, f"Model     {cfg['default_model']}   cookie: {'yes' if cfg['cookie_file'] else 'no'}"
                  f"   proxy: {cfg['proxy'] or 'no'}")
        put(5, 2, eng.test)
        put(7, 2, "── engine log " + "─" * max(0, w - 20), curses.A_DIM)
        for i, line in enumerate(tail(max(1, h - 12))):
            put(8 + i, 2, line)
        put(h - 3, 2, msg, curses.A_BOLD)
        put(h - 1, 1, "[s]tart/stop [r]estart [t]est [k]ey [c]ookie [p]roxy [q]uit", curses.A_REVERSE)
        scr.refresh()

        ch = scr.getch()
        if ch == -1:
            continue
        k = chr(ch).lower() if 0 < ch < 256 else ""
        if k == "q":
            break
        elif k == "s":
            if eng.running():
                eng.stop()
                msg = "engine stopped"
            else:
                eng.start()
                msg = "engine starting"
        elif k == "r":
            eng.stop()
            eng.start()
            msg = "engine restarted"
        elif k == "t":
            if eng.ready:
                eng.run_test()
            else:
                msg = "engine not ready - start it first"
        elif k == "k":
            reveal = not reveal
        elif k == "c":
            path = prompt(scr, "cookie file (blank = none): ")
            if path and not Path(path).expanduser().is_file():
                msg = "cookie file not found"
            else:
                cfg["cookie_file"] = str(Path(path).expanduser().resolve()) if path else None
                save(cfg)
                msg = "cookie saved - press r to apply"
        elif k == "p":
            proxy = prompt(scr, "proxy e.g. http://127.0.0.1:7890 (blank = none): ")
            cfg["proxy"] = proxy or None
            save(cfg)
            msg = "proxy saved - press r to apply"


USAGE = """usage: gravita [--version] [--help]

Opens the gravita terminal UI and starts the engine.
Engine listens on http://127.0.0.1:8081/v1. Keys: s r t k c p q."""


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("-V", "--version"):
            print(f"gravita {__version__}")
            return
        print(USAGE)
        return
    bootstrap()
    eng = Engine()
    try:
        curses.wrapper(ui, eng)
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()
        print("gravita: engine stopped")
