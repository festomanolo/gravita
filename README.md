# gravita

**Turn Google Gemini's web app into a free, OpenAI-compatible API, with one command.**

[![PyPI](https://img.shields.io/pypi/v/nolo-gravita?color=blue)](https://pypi.org/project/nolo-gravita/)
[![Python](https://img.shields.io/pypi/pyversions/nolo-gravita)](https://pypi.org/project/nolo-gravita/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```bash
pip install nolo-gravita
gravita
```

That's it. `gravita` starts the engine, opens a terminal dashboard, and serves an OpenAI-style API
at **`http://127.0.0.1:8081/v1`**. Point any OpenAI-compatible app at it: Cherry Studio, ChatBox,
the OpenAI SDK, Codex CLI, Gemini CLI, or plain `curl`.

---

## Why gravita

- **One command.** No config to write first. Install, run, done.
- **A dashboard, not a wall of logs.** Status, base URL, API key, a live engine log, and a test button, all in one screen.
- **Free.** Works with a normal anonymous Gemini session. No API key from Google required.
- **Works with the tools you already use.** OpenAI chat completions, the Responses API, and Google's native Gemini endpoints.
- **Safe by default.** Listens on `127.0.0.1` and issues a random API key on first run.
- **Small.** Pure Python plus `httpx`. One vendored engine file.

## Install

Requires **Python 3.8+** on **macOS or Linux**. Windows users: run it under WSL.

```bash
pip install nolo-gravita
```

Or from source:

```bash
git clone https://github.com/festomanolo/gravita.git
cd gravita
pip install -e .
```

## Quick start

```bash
gravita
```

On first run gravita creates `~/.gravita/config.json` with a random API key, then starts the engine.
Wait for the status line to read **● ready**, then try it:

```bash
curl http://127.0.0.1:8081/v1/chat/completions \
  -H "Authorization: Bearer $(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.gravita/config.json")))["api_keys"][0])')" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.6-flash","messages":[{"role":"user","content":"Hello!"}]}'
```

The dashboard's **API key** line shows your key. Press `k` to reveal it in full.

## The dashboard

```
 gravita 1.0.0   ● ready  pid 4312  up 92s
  Base URL  http://127.0.0.1:8081/v1
  API key   sk-gravita-3f9a...
  Model     gemini-3.6-flash   cookie: no   proxy: no
  test ok: Ok! How can I help you today?
  ── engine log ──────────────────────────────
  gemini-web2api v1.1.0
  Listening: http://0.0.0.0:8081
  ...
  [s]tart/stop [r]estart [t]est [k]ey [c]ookie [p]roxy [q]uit
```

| Key | Action |
|-----|--------|
| `s` | Start or stop the engine |
| `r` | Restart the engine (applies cookie and proxy changes) |
| `t` | Send one tiny test request (`gemini-flash-lite`, "Reply: ok") |
| `k` | Reveal or hide the API key |
| `c` | Set a Gemini cookie file for Pro routing (blank clears it) |
| `p` | Set an HTTP proxy, such as `http://127.0.0.1:7890` |
| `q` | Quit (stops the engine) |

## Connect your apps

| Setting | Value |
|---------|-------|
| Base URL | `http://127.0.0.1:8081/v1` |
| API key | the key shown in gravita (`~/.gravita/config.json` → `api_keys`) |
| Model | `gemini-3.6-flash` |

**OpenAI Python SDK**

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8081/v1", api_key="sk-gravita-...")
resp = client.chat.completions.create(
    model="gemini-3.6-flash",
    messages=[{"role": "user", "content": "Explain quantum computing in one paragraph."}],
)
print(resp.choices[0].message.content)
```

**Tool calling** works in OpenAI format (`tools=[...]`), and **image input** works with `image_url` parts
(HTTP URLs or base64 data URLs).

**Gemini CLI**

```bash
export GEMINI_API_KEY=sk-gravita-...
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8081
gemini
```

## Antigravity CLI (agy) + Gravitas

gravita bundles [Gravitas](https://github.com/udaysharmadev/Gravitas) (MIT), a reliability layer for coding
agents, as an `agy` plugin. Once installed it loads on every agy session (read-before-edit, scoped writes,
evidence before "done").

```bash
gravita setup     # install the Gravitas plugin into agy (also: press i in the dashboard)
gravita doctor    # print the health checklist; non-zero exit if something is broken
gravita agy ...   # launch agy; prints that it uses its own account + the Gravitas plugin state
```

The dashboard has a **health** panel (engine, agy, python3, Gravitas plugin, agy backend, Pro cookie) and a
**Next:** line that tells you the first thing to fix. Note: tested against agy, it ignores
`GEMINI_API_KEY` / `GOOGLE_GEMINI_BASE_URL`, so agy always runs on its own signed-in account. The gravita
API serves other apps (Cherry Studio, Codex, the OpenAI SDK, ...), not agy itself.
Bundled Gravitas snapshot: upstream commit `f76b0d9`.

## Models

| Model | Best for | Output |
|-------|----------|--------|
| `gemini-3.6-flash` | All-round default (alias: `gemini-3.5-flash`) | ~12k chars |
| `gemini-3.5-flash-thinking` | Longest answers, extended thinking | ~20k chars |
| `gemini-3.5-flash-thinking-lite` | Adaptive thinking depth | ~15k chars |
| `gemini-3.1-pro` | Math and code (needs a Pro cookie for real Pro routing) | ~12k chars |
| `gemini-auto` | Let Gemini pick | varies |
| `gemini-flash-lite` | Fastest, lightweight | ~10k chars |

Control thinking depth by appending `@think=N` to a thinking model: `0` is deepest (the default), `4` is shallowest.

```
gemini-3.5-flash-thinking@think=2
```

## Configuration

Settings live in `~/.gravita/config.json`. Edit it directly or use the dashboard keys.

| Field | Default | Purpose |
|-------|---------|---------|
| `port` | `8081` | Port the API listens on |
| `host` | `127.0.0.1` | Bind address. Use `0.0.0.0` to expose it on your network (set an API key first) |
| `api_keys` | `["sk-gravita-…"]` | Bearer keys. Empty list means no auth |
| `default_model` | `gemini-3.6-flash` | Model shown in the dashboard |
| `cookie_file` | `null` | Path to a Gemini cookie file (see below) |
| `proxy` | `null` | HTTP proxy for reaching Gemini |
| `temporary_chats` | `false` | Use Gemini temporary chats instead of account history |
| `retry_attempts` / `retry_delay_sec` | `3` / `2` | Retry policy for upstream errors |
| `request_timeout_sec` | `180` | Upstream timeout |

Restart the engine (`r`) after editing the file.

### Pro routing (optional)

Anonymous access works for every model. `gemini-3.1-pro` only routes to real Pro with a
**Gemini Advanced** cookie:

1. Sign in to [gemini.google.com](https://gemini.google.com) with your Advanced account.
2. In DevTools → Application → Cookies, copy `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, and `__Secure-1PSID`.
3. Save them on one line in a file, for example `~/cookie.txt`:
   ```
   SID=...; HSID=...; SSID=...; APISID=...; SAPISID=...; __Secure-1PSID=...
   ```
4. Press `c` in gravita and enter the path, then `r` to restart.

### Behind a proxy

If `gemini.google.com` is unreachable from your network, press `p` and enter your proxy
(for example `http://127.0.0.1:7890`), then `r`. Standard `HTTPS_PROXY` environment variables also work.

## How it works

gravita runs [gemini-web2api](https://github.com/Sophomoresty/gemini-web2api), which speaks to
the same streaming endpoint the Gemini web app uses and translates requests and responses between
the OpenAI format and Gemini's internal format. The model is chosen by the `MODE_CATEGORY` field
in the request payload.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Status stays **starting** | Check the log in the dashboard. Gemini may be blocked: set a proxy with `p`. |
| `content: null` in responses under Docker bridge networking | Use host networking. Upstream rejects some Docker NAT ranges. |
| HTTP 401 | Send `Authorization: Bearer <key>` with the key from the dashboard. |
| `exited (1)` | The port is probably in use. Change `port` in `~/.gravita/config.json`. |
| Xsrf or 400 errors with a cookie | Refresh Gemini in the browser, then update the cookie file and restart. |

Logs live at `~/.gravita/engine.log`.

## Limits

- **Single turn.** Each request is an independent conversation. Multi-turn history is included in the prompt.
- **Not real Pro without a cookie.** Without a Gemini Advanced cookie, `gemini-3.1-pro` uses Flash.
- **Rate limits.** Google may throttle heavy use.
- **Unofficial.** This project reverse-engineers a web endpoint. It may break when Google changes it, and it may conflict with Google's terms of service. Use it for personal experimentation.

## Credits

- Engine: [gemini-web2api](https://github.com/Sophomoresty/gemini-web2api) by Sophomoresty (MIT). A copy is bundled in `gravita/engine/`, with its license.
- gravita itself: MIT, see [LICENSE](LICENSE).
