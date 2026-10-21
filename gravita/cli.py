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

from gravita import __version__, agy, gemini

try:
    import curses
except ImportError:  # Windows has no curses
    sys.exit("gravita needs a POSIX terminal (macOS or Linux).")

ENGINE = Path(__file__).resolve().parent / "engine" / "gemini_web2api.py"
HOME = Path.home() / ".gravita"
CONF = HOME / "config.json"
LOG = HOME / "engine.log"
ONBOARDED = HOME / "onboarded"
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
                self.checks = agy.checks(load(), self.ready) + gemini.checks(load())
            time.sleep(4)

    def toggle_gravitas(self):
        def work():
            path = agy.find_agy()
            if not path:
                self.test = "agy not found"
                return
            ok, text = agy.set_enabled(path, agy.plugin_state(path) != "enabled")
            self.checks = agy.checks(load(), self.ready)
            self.test = "gravitas: " + text
        threading.Thread(target=work, daemon=True).start()

    def setup_gemini(self):
        def work():
            self.busy = "setting up Gemini CLI + Gravitas skills..."
            ok, text = (True, "already installed") if gemini.find_gemini() else gemini.install_cli()
            if ok:
                gemini.prepare_home()
            self.busy = ""
            self.checks = agy.checks(load(), self.ready) + gemini.checks(load())
            self.test = ("gemini: " if ok else "gemini setup failed: ") + text
        threading.Thread(target=work, daemon=True).start()

    def install_gravitas(self):
        def work():
            self.busy = "installing Gravitas into agy..."
            path = agy.find_agy()
            ok, text = agy.install(path) if path else (False, "agy not found")
            self.busy = ""
            self.checks = agy.checks(load(), self.ready) + gemini.checks(load())
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


MARKS = {agy.OK: ("✔", 1), agy.WARN: ("!", 2), agy.FAIL: ("✖", 3)}


def draw_checks(put, y, checks):
    for i, (label, st, detail, fix) in enumerate(checks):
        mark, col = MARKS[st]
        put(y + i, 2, mark, curses.color_pair(col) | curses.A_BOLD)
        put(y + i, 4, f"{label:<18}{detail}")
        if fix:
            put(y + i, 4 + 18 + len(detail) + 2, "→ " + fix, curses.A_DIM)


PAGES = [
    ("Welcome to gravita", [
        "gravita does two separate things:",
        "",
        "  1. Serves a free OpenAI-compatible API (Gemini web) at http://127.0.0.1:{port}/v1",
        "     for apps like Cherry Studio, Codex, the OpenAI SDK or curl.",
        "  2. Installs Gravitas into the Antigravity CLI (agy) as a plugin.",
        "",
        "Important: agy does NOT use the gravita API. Tested: it ignores custom endpoints",
        "and always runs on its own signed-in account.",
        "To use the gravita API with an agent, run  gravita gemini  (the Gemini CLI, which",
        "does honor a custom endpoint) - Gravitas skills come preloaded. Press m to set it up.",
    ]),
    ("Setup checklist", None),
    ("How Gravitas behaves in agy", [
        "Once installed, Gravitas loads on every agy session and gates tool calls.",
        "",
        "Verified here: with no task contract, agy is blocked from running shell",
        "commands and writing files (reads still work). Upstream's way to start a task",
        "is to ask for it by name, e.g.  \"Use Gravitas to fix this bug and verify it\".",
        "Headless runs (agy -p) cannot answer permission prompts.",
        "",
        "Want plain agy back? Press g in the dashboard to switch the plugin off and on.",
    ]),
    ("You're set", [
        "Dashboard keys:  s start/stop   r restart   t test   i install Gravitas",
        "                 g Gravitas on/off   m Gemini CLI   o guide   k key   c cookie   p proxy",
        "",
        "Terminal:  gravita doctor   print the health checklist",
        "           gravita setup    install/repair the Gravitas plugin",
        "           gravita gemini   Gemini CLI on the gravita API, Gravitas skills preloaded",
        "           gravita onboard  show this guide again",
    ]),
]


def onboarding(scr, eng):
    """Full-screen first-run guide. Enter/right = next, b/left = back, i = install, q/Esc = close."""
    cfg = load()
    page = 0
    scr.timeout(400)
    while True:
        h, w = scr.getmaxyx()
        scr.erase()
        title, lines = PAGES[page]

        def put(y, x, text, attr=0):
            try:
                scr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

        put(0, 1, f"gravita setup  {page + 1}/{len(PAGES)}", curses.A_DIM)
        put(2, 2, title, curses.A_BOLD)
        if lines is None:
            draw_checks(put, 4, eng.checks)
            put(5 + len(eng.checks), 2, eng.busy or "Press i to install/repair Gravitas, s to start the engine.")
        else:
            for i, line in enumerate(lines):
                put(4 + i, 2, line.format(port=cfg["port"]))
        put(h - 1, 1, "[enter] next  [b]ack  [i]nstall Gravitas  [s]tart engine  [q] close", curses.A_REVERSE)
        scr.refresh()
        ch = scr.getch()
        k = chr(ch).lower() if 0 < ch < 256 else ""
        if k == "q" or ch == 27:
            break
        elif k == "i":
            eng.install_gravitas()
        elif k == "s":
            eng.start()
        elif k == "b" or ch == curses.KEY_LEFT:
            page = max(0, page - 1)
        elif ch in (10, 13, curses.KEY_ENTER, curses.KEY_RIGHT) or k == " ":
            if page == len(PAGES) - 1:
                break
            page += 1
    try:
        ONBOARDED.write_text("1\n")
    except OSError:
        pass
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
    if not ONBOARDED.exists():
        onboarding(scr, eng)

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
        draw_checks(put, 8, eng.checks)
        row = 8 + len(eng.checks)
        todo = next((c for c in eng.checks if c[1] == agy.FAIL), None)
        nxt = eng.busy or (f"Next: {todo[0]} - {todo[3] or todo[2]}" if todo else "All set. agy is ready.")
        put(row, 2, nxt, curses.A_BOLD)
        put(row + 2, 2, "── engine log " + "─" * max(0, w - 20), curses.A_DIM)
        for i, line in enumerate(tail(max(0, h - row - 7))):
            put(row + 3 + i, 2, line)
        put(h - 3, 2, eng.blocked or ("" if eng.ready and msg == "engine starting" else msg),
            curses.A_BOLD | (curses.color_pair(3) if eng.blocked else 0))
        put(h - 1, 1, "[s]tart/stop [r]estart [t]est [i]nstall Gravitas  [g] on/off  [m] gemini [o]nboarding [k]ey [c]ookie [p]roxy [q]uit", curses.A_REVERSE)
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
        elif k == "g":
            eng.toggle_gravitas()
            msg = "toggling Gravitas..."
        elif k == "m":
            eng.setup_gemini()
            msg = "setting up Gemini CLI..."
        elif k == "o":
            onboarding(scr, eng)
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


def run_gemini(argv):
    """Ensure the engine is up (starting and later stopping it if we own it), then run the Gemini CLI."""
    eng = Engine()
    eng.start()
    if eng.blocked:
        print("gravita: " + eng.blocked, file=sys.stderr)
        return 1
    print("gravita: waiting for the engine...", file=sys.stderr)
    deadline = time.time() + 90
    while not eng.ready and time.time() < deadline:
        time.sleep(0.5)
    if not eng.ready:
        eng.stop()
        print(f"gravita: engine did not become ready - see {LOG}", file=sys.stderr)
        return 1
    try:
        return gemini.run(load(), argv)
    finally:
        eng.stop()


def onboard_standalone(scr):
    curses.start_color()
    curses.use_default_colors()
    for i, color in ((1, curses.COLOR_GREEN), (2, curses.COLOR_YELLOW), (3, curses.COLOR_RED)):
        curses.init_pair(i, color, -1)
    onboarding(scr, Engine())


USAGE = """usage: gravita [--version] [--help] [setup | doctor | onboard | gemini [args...] | agy [agy args...]]

  (no args)  open the terminal UI and start the engine (Gravitas health + onboarding shown)
  setup      install the Gravitas plugin into agy so it loads on every session
  doctor     print the health checklist and exit non-zero if something is broken
  gemini ... run the Gemini CLI on the gravita API with Gravitas skills preloaded
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
            rows = agy.checks(cfg, up) + gemini.checks(cfg)
            for label, st, detail, fix in rows:
                print(f"{ {'ok': '✔', 'warn': '!', 'fail': '✖'}[st] } {label:<18}{detail}" + (f"  -> {fix}" if fix else ""))
            sys.exit(1 if any(r[1] == agy.FAIL for r in rows) else 0)
        elif cmd == "onboard":
            bootstrap()
            curses.wrapper(onboard_standalone)
        elif cmd == "gemini":
            bootstrap()
            sys.exit(run_gemini(sys.argv[2:]))
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
