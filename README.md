# VFS Global (Netherlands, Tehran) Appointment Monitor

A fork of `rotterdam_appointment_monitor`: the engine (scheduling, randomized
interval, state file, change detection, Telegram plumbing, single-instance lock)
is reused unchanged, while everything VFS-specific lives in a separate adapter.

It watches the VFS Global appointment pages for the Netherlands services in
Tehran and messages you on Telegram when something looks bookable - including a
screenshot, so you can verify it yourself. It never books anything and never
tries to bypass a CAPTCHA or bot check.

## What it does on every cycle

1. Reads the official NetherlandsWorldwide appointment page and re-discovers the
   current VFS appointment link. The `P=` token in that link is session scoped
   and expires, so a hardcoded URL would silently stop working.
2. Loads that page with Playwright (locally installed Google Chrome) and
   classifies what comes back.
3. Sends Telegram messages when the page looks bookable, when the detected slot
   changes, and when it can no longer see the calendar.

## Read this first: where it can run

`vfsvisaonline.com` sits behind Cloudflare, and the outcome depends on the IP you
connect from:

| Connecting from | Result |
|---|---|
| Dutch residential line (tested 2026-09-21) | hard block: HTTP 403, "Sorry, you have been blocked" |
| A server / datacenter IP in another country | soft check: "Just a moment..." interstitial |

The hard block survived `requests`, Playwright's Chromium **and** a real Chrome
(`channel="chrome"`) while other Cloudflare sites answered 200, so it is a country
rule on their side and no code can change it. The soft check is a different thing:
it normally clears by itself within seconds.

The monitor therefore:
- waits the check out (`CHALLENGE_WAIT_SECONDS`, polled every 3 s) instead of giving up,
- keeps the clearance cookie in a persistent browser profile (`BROWSER_PROFILE_DIR`),
  so later cycles usually pass without a challenge at all,
- reports "still challenged" as its own status (never as "no appointments").

**Supported deployment: a server outside the Netherlands** (Oracle Cloud Always
Free, non-NL region). Run `recon_vfs.py` on that machine to see which of the two
outcomes it gets.

## Files

| File | Role |
|---|---|
| `monitor.py` | shared engine: run modes, interval randomization, state + change detection, Telegram sends, heartbeat, lock |
| `vfs_adapter.py` | all VFS-specific logic: URL discovery, page classification, Playwright check, detail extraction, message text, screenshots |
| `config.py` | markers, statuses, cadence, browser options (all environment driven) |
| `recon_vfs.py` | non-interactive recon: entry page + VFS page, saves HTML/text/PNG to `recon_out/`, prints markers and a verdict |
| `recon_control.py` | control test comparing vfsvisaonline.com against other Cloudflare hosts |
| `check_telegram.py` | sends one test message to each configured chat |
| `deploy/install_server.sh` | one-command setup on an Ubuntu server + systemd timer |
| `upload_to_server.ps1` | copies the project from Windows to the server and installs it |
| `publish_to_github.ps1` | publishes to GitHub and starts the free Actions monitor |
| `set_telegram.bat`, `setup_and_check.bat`, `register_task.ps1` | Windows helpers (local testing) |
| `test_classify.py`, `test_parser.py`, `test_run_check.py` | offline tests (no network) |
| `test_appointment_change.py` | prints the exact messages the monitor can send; `--send` delivers them |
| `run_vfs_monitor.bat` | one check cycle, for Windows Task Scheduler |
| `register_task.ps1` | registers (or removes) a 30-minute Windows scheduled task |

## Statuses

Every cycle ends in exactly one status, stored in `vfs_state.json`:

| Status | Meaning | Telegram |
|---|---|---|
| `available` | date/list UI detected | alert + screenshot |
| `none` | "no appointments" text found | heartbeat only |
| `blocked` | hard Cloudflare block, also HTTP 403/429 with no challenge text | state-change alert |
| `challenge` | "Just a moment..." check that did not clear in time | state-change alert |
| `captcha` | human verification page | state-change alert |
| `queue` | virtual waiting room | state-change alert |
| `login_required` | page wants credentials | state-change alert |
| `error` | unexpected page or failure | state-change alert |

Blocked, captcha, queue, login and unknown pages are **never** reported as "no
appointments": a monitor that cannot see the calendar says so instead of staying
silent. This is the single most important design rule in this fork.

## Setup

```powershell
cd <this folder>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
copy .env.sample .env      # then fill in the Telegram token and chat ids
```

Browsers are installed per user, so an existing `playwright install` from another
project is reused. `BROWSER_CHANNEL=chrome` uses your locally installed Chrome.

## Running on a server (Oracle Cloud Always Free and friends)

```bash
# on the server, after copying the project folder there
cd ~/vfs_tehran_slot_monitor
chmod +x deploy/install_server.sh
./deploy/install_server.sh
```

From Windows you can do both steps in one go: right-click `upload_to_server.ps1` →
*Run with PowerShell* (it asks for the server IP and your SSH key file).

The installer:

1. installs Chromium, its libraries and `xvfb` (the virtual screen),
2. creates `.venv` and installs `requirements.txt`,
3. installs a **systemd timer** that runs one cycle every 10 minutes and survives
   reboots (the monitor's own randomized window decides whether a cycle really
   checks),
4. runs `recon_vfs.py` once so you immediately see whether that server can reach
   the site.

The browser runs under `xvfb-run` with `PLAYWRIGHT_HEADLESS=False`, because a
browser that has a real display is far less likely to be stopped by Cloudflare than
a headless one. `systemd`'s `Environment=` wins over `.env` (python-dotenv does not
override variables that are already set).

Useful commands:

```bash
sudo systemctl start vfs-monitor.service    # run one cycle now
tail -f vfs_monitor.log                     # live log
journalctl -u vfs-monitor.service -n 50     # last run's output
systemctl list-timers | grep vfs            # is the schedule alive?
sudo systemctl disable --now vfs-monitor.timer   # stop the schedule
```

Notes for servers:

- use a **non-Netherlands** region (Amsterdam is an Oracle region, and the
  Netherlands is precisely the country that gets blocked),
- give the instance at least ~2 GB RAM; the 1 GB Always Free shape is too small for
  Chromium,
- no inbound ports need to be opened — the monitor only connects outward,
- the persistent profile in `BROWSER_PROFILE_DIR` allows only one process at a time,
  which the built-in lock file already enforces.

## Running

```powershell
.\.venv\Scripts\python.exe monitor.py --once        # one cycle, Task Scheduler friendly
.\.venv\Scripts\python.exe monitor.py --scheduler   # continuous (APScheduler)
.\.venv\Scripts\python.exe monitor.py --test        # one cycle with normal logging
```

`--once` is safe to call every few minutes: the state file decides whether the
randomized interval (1200-2400 s by default) has elapsed.

To keep it running automatically on Windows:

```powershell
.\register_task.ps1            # registers a task that runs run_vfs_monitor.bat every 30 min
.\register_task.ps1 -Remove    # removes it again
```

## Tuning the detection (expected work)

Start with recon on the machine that has access:

```powershell
.\.venv\Scripts\python.exe recon_vfs.py
```

Then compare `recon_out/vfs_*.txt` with the marker lists in `config.py` and adjust
`NO_APPOINTMENT_MESSAGES`, `AVAILABILITY_MARKERS`, `BLOCKED_MARKERS`,
`CAPTCHA_MARKERS`, `QUEUE_MARKERS`, `LOGIN_MARKERS`.

If the real flow needs extra clicks (country, centre, service, login), add them to
`vfs_adapter.advance_flow()` and keep `FLOW_ENABLED=True`. Guard every click with
try/except.

When no marker matches, the cycle ends as `error` and `vfs_monitor.log` records the
page title, URL, first 1200 characters and the visible controls, so the markers can
be tuned from the log alone.

To sit behind a login, save a session once and point `PLAYWRIGHT_STORAGE_STATE` at it:

```powershell
.\.venv\Scripts\playwright.exe codegen --save-storage=storage_state.json "<appointment url>"
```

## Free alternative: run it on GitHub Actions

No server needed. `.github/workflows/vfs-monitor.yml` runs one check cycle on
GitHub's own machines every 15 minutes and can also be started by hand
(*Actions → VFS Tehran appointment monitor → Run workflow*).

Setup:

1. push this folder to a GitHub repository (private is fine; public uses no minutes),
2. add repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   `TELEGRAM_STATUS_CHAT_ID`, `TELEGRAM_ALERT_CHAT_ID`,
3. start it once by hand and watch the log.

It caches `vfs_state.json` and `.browser_profile` between runs, so the Cloudflare
clearance and the monitor's own state survive. Screenshots, the log and `recon_out/`
are uploaded as a downloadable artifact each run.

Trade-offs to know: GitHub's cron is not exact (a few minutes of delay is normal),
and scheduled workflows are paused after 60 days without repository activity.

It is also the cheapest way to answer "does a non-Dutch IP get in?": GitHub's
runners sit outside the Netherlands, so the first manual run is a free test.

## Routing the browser through a proxy

If this machine's address is refused but another exit point works, point the browser
at it without touching any code:

```
BROWSER_PROXY_SERVER=http://host:port
BROWSER_PROXY_USERNAME=optional
BROWSER_PROXY_PASSWORD=optional
```

Only the browser traffic uses it; the official-page request stays direct.

## Notes and limits

- Cadence is deliberately conservative (20-40 min) because the site actively
  protects itself; do not lower it without a reason.
- Nothing is booked automatically and no CAPTCHA is bypassed.
- Secrets stay in `.env` (gitignored); `storage_state.json` is gitignored too.
- If a `vfs_state.json` lock/state file collision ever occurs with the Rotterdam
  monitor, check `LOCK_FILE`, `STATE_FILE` and `LOG_FILE` - they are deliberately
  different per project so both monitors can run side by side.
