"""gravita terminal UI: start, watch and talk to the local Gemini-to-OpenAI engine."""
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from gravita import __version__, agy

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
        self.checks = []
        self.busy = ""
        self.external = False   # adopted an engine we did not spawn; never kill it
        self.blocked = ""       # port held by something that is not a usable engine
        threading.Thread(target=self._poll, daemon=True).start()
        threading.Thread(target=self._health, daemon=True).start()

    def _health(self):
        while True:
            if not self.busy:
                self.checks = agy.checks(load(), self.ready)
            time.sleep(4)

    def install_gravitas(self):
        def work():
            self.busy = "installing Gravitas into agy..."
            path = agy.find_agy()
            ok, text = agy.install(path) if path else (False, "agy not found")
            self.busy = ""
            self.checks = agy.checks(load(), self.ready)
            self.test = ("gravitas: " if ok else "gravitas install failed: ") + text
        threading.Thread(target=work, daemon=True).start()

    def running(self):
        return self.external or (self.p is not None and self.p.poll() is None)

    def probe(self, cfg):
        """'engine' if a gravita-compatible engine answers on the port, 'busy' if something else
        holds it, 'free' otherwise."""
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{cfg['port']}/v1/models", headers=auth(cfg))
            with OPENER.open(req, timeout=2) as r:
                return "engine" if r.status == 200 else "busy"
        except urllib.error.HTTPError:
            return "busy"
        except OSError:
            pass
        with socket.socket() as sk:
            sk.settimeout(1)
            return "busy" if sk.connect_ex(("127.0.0.1", int(cfg["port"]))) == 0 else "free"

    def start(self):
        if self.running():
            return
        self.cfg = load()
        self.blocked = ""
        found = self.probe(self.cfg)
        if found == "engine":
            self.external, self.started = True, time.time()
            return
        if found == "busy":
            self.blocked = (f"port {self.cfg['port']} is in use by another program "
                            f"(or an engine with a different key) - change 'port' in {CONF}")
            return
        with open(LOG, "ab") as log:
            log.write(f"\n--- start {time.strftime('%H:%M:%S')} ---\n".encode())
            self.p = subprocess.Popen(
                [sys.executable, "-u", str(ENGINE), "--config", str(CONF)],
                stdout=log, stderr=subprocess.STDOUT, cwd=str(HOME),
            )
        self.started = time.time()

    def stop(self):
        if self.external:
            self.external = False
            self.ready = False
            return
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
        if eng.external:
            state, color = ("ready" if eng.ready else "starting"), (1 if eng.ready else 2)
            state += f"  (already running on :{cfg['port']}, not managed by this window)"
        elif eng.running():
            state, color = ("ready", 1) if eng.ready else ("starting", 2)
            state += f"  pid {eng.p.pid}  up {int(time.time() - eng.started)}s"
        elif eng.blocked:
            state, color = "blocked - port in use", 3
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
        put(7, 2, "── health " + "─" * max(0, w - 14), curses.A_DIM)
        marks = {agy.OK: ("✔", 1), agy.WARN: ("!", 2), agy.FAIL: ("✖", 3)}
        for i, (label, st, detail, fix) in enumerate(eng.checks):
            mark, col = marks[st]
            put(8 + i, 2, mark, curses.color_pair(col) | curses.A_BOLD)
            put(8 + i, 4, f"{label:<18}{detail}")
            if fix:
                put(8 + i, 4 + 18 + len(detail) + 2, "→ " + fix, curses.A_DIM)
        row = 8 + len(eng.checks)
        todo = next((c for c in eng.checks if c[1] == agy.FAIL), None)
        nxt = eng.busy or (f"Next: {todo[0]} - {todo[3] or todo[2]}" if todo else "All set. agy is ready.")
        put(row, 2, nxt, curses.A_BOLD)
        put(row + 2, 2, "── engine log " + "─" * max(0, w - 20), curses.A_DIM)
        for i, line in enumerate(tail(max(0, h - row - 7))):
            put(row + 3 + i, 2, line)
        put(h - 3, 2, eng.blocked or msg,
            curses.A_BOLD | (curses.color_pair(3) if eng.blocked else 0))
        put(h - 1, 1, "[s]tart/stop [r]estart [t]est [i]nstall-gravitas [k]ey [c]ookie [p]roxy [q]uit", curses.A_REVERSE)
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
        elif k == "i":
            eng.install_gravitas()
            msg = "installing Gravitas..."
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


USAGE = """usage: gravita [--version] [--help] [setup | doctor | agy [agy args...]]

  (no args)  open the terminal UI and start the engine (Gravitas health + onboarding shown)
  setup      install the Gravitas plugin into agy so it loads on every session
  doctor     print the health checklist and exit non-zero if something is broken
  agy ...    launch agy and print which backend and plugin state it runs with
Engine listens on http://127.0.0.1:8081/v1. Keys: s r t i k c p q."""


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ("-V", "--version"):
            print(f"gravita {__version__}")
        elif cmd == "setup":
            path = agy.find_agy()
            ok, text = agy.install(path) if path else (False, "agy not found")
            print(("ok: " if ok else "failed: ") + text)
            sys.exit(0 if ok else 1)
        elif cmd == "doctor":
            bootstrap()
            cfg = load()
            try:
                with OPENER.open(urllib.request.Request(
                        f"http://127.0.0.1:{cfg['port']}/v1/models", headers=auth(cfg)), timeout=2) as r:
                    up = r.status == 200
            except Exception:
                up = False
            rows = agy.checks(cfg, up)
            for label, st, detail, fix in rows:
                print(f"{ {'ok': '✔', 'warn': '!', 'fail': '✖'}[st] } {label:<18}{detail}" + (f"  -> {fix}" if fix else ""))
            sys.exit(1 if any(r[1] == agy.FAIL for r in rows) else 0)
        elif cmd == "agy":
            bootstrap()
            agy.launch(load(), sys.argv[2:])
        else:
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
