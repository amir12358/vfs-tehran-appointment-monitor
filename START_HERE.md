# START HERE — VFS Tehran appointment monitor

*You do not need to understand any code. Everything below is double-clicking.*

## What this does

Every 20–40 minutes it quietly opens the appointment website of the Netherlands
(VFS Global, Tehran), looks at whether appointment slots are visible, and sends
**you a Telegram message** when something looks free — including a **picture of the
page** so you can judge for yourself.

It never books anything on its own and never solves a captcha. You always book
manually.

## Where it runs

The website protects itself with Cloudflare, and what you get depends on where you
connect from:

- From your Rotterdam home line: a hard **“Sorry, you have been blocked”** page.
  No setting can change that — it is a country rule on their side (other websites
  work perfectly from the same computer, which is how I know it is their rule).
- From a server abroad (I tested): a soft **“Just a moment…”** check instead. That is
  **not** a block — a real browser normally passes it on its own within seconds.

That is why this now runs on your Oracle server: the program waits out the
“Just a moment…” check, keeps the clearance cookie, and then reads the page.

**Pick a non-Netherlands region** (Frankfurt, Zurich, Paris or Dubai). Amsterdam is
also an Oracle region, but the Netherlands is exactly the country that gets blocked.

---

## Part 1 — Create the Oracle server (20 minutes, once)

1. Go to <https://cloud.oracle.com>, sign in, and press **Create instance**.
2. **Image:** Ubuntu 22.04 (or 24.04).
   **Shape:** `VM.Standard.A1.Flex` with 2 OCPU / 12 GB — that shape is Always Free.
   (The tiny 1 GB shape is too small to run a browser.)
3. **Region:** a non-Netherlands one — Frankfurt, Zurich, Paris or Dubai.
4. **SSH keys:** choose *Generate a key pair for me* and download the **private key**
   file. You need it in step 7. Without it you cannot get in.
5. Leave the network settings exactly as they are — **no ports need to be opened**,
   because the monitor only connects outward.
6. Press **Create** and wait until the instance shows *Running*.
7. On your own computer, open this folder and **right-click
   `upload_to_server.ps1` → Run with PowerShell**. It asks for two things:
   - the server's **Public IP address** (shown on the Oracle instance page)
   - the **full path to the key file** from step 4
8. Wait a few minutes. The last lines it prints are the **verdict** (you also get a
   Telegram message about the result) — that verdict is the important part:

| Verdict on the server | Meaning | What to do |
|---|---|---|
| CLOUDFLARE CHECK, NO SLOTS or POSSIBLE AVAILABILITY | the server reached the real website | nothing — it is already scheduled every 10 minutes |
| BLOCKED | this server IP is refused too | send me the report; we try another region or another route |
| ERROR / UNKNOWN | the page looks different from what I predicted | send me `recon_out/report.txt` and the newest `vfs_*.txt` |

9. You can check the Telegram side any time: on the server, inside the project
   folder, run `.venv/bin/python check_telegram.py`.

If any step of 1–6 is unclear, send me a screenshot of that Oracle screen and I will
tell you exactly what to choose.

---

## Part 2 — Telegram setup (5 minutes, done once)

1. On your phone, open Telegram and search for **@BotFather** → press START.
2. Send: `/newbot`
3. Give it a name (for example `VFS Tehran Monitor`) and then a username that ends
   with `bot` (for example `vfs_tehran_monitor_bot`).
4. BotFather answers with a **token** that looks like `123456789:AAH...`. Copy it.
5. Open a chat with your new bot and send `/start` once — without this the bot is
   not allowed to message you.
6. In a browser, open this address, replacing the token with yours:

   `https://api.telegram.org/bot<PASTE_YOUR_TOKEN_HERE>/getUpdates`

   Find `"chat":{"id":123456789` → that number is your **chat ID**.
7. Double-click **`set_telegram.bat`** on the computer, paste the token and the chat
   ID when asked. You should receive one test message immediately.

Keep the token private — anyone who has it can send messages as your bot.

---

## Part 3 — Leave it running

Nothing to do — the installer already set up a schedule on the server that runs a
check every 10 minutes and continues after a reboot. The program itself deliberately
only really checks every 20–40 minutes, so that the website does not start blocking
the server.

Handy commands (type them in the server window, or just ask me):

- `sudo systemctl start vfs-monitor.service` — run one check right now
- `tail -f vfs_monitor.log` — watch what it is doing
- `systemctl list-timers | grep vfs` — confirm the schedule is alive

---

## Part 4 — What the messages mean

| Message | Meaning | What to do |
|---|---|---|
| 🚨 VFS Tehran appointment possible | the page looked bookable | open the website now, verify with the picture, book |
| status changed to *blocked* | the site refused our computer | nothing yet; it keeps retrying. If it stays blocked for hours, tell me |
| status changed to *challenge* | the “Just a moment…” check did not clear in time | usually harmless, the next run often passes; tell me if it repeats |
| status changed to *login required* | the site now asks for a login | tell me |
| status changed to *captcha* | the site asks for a human check | do nothing — we never bypass it; tell me if it repeats |
| no appointments / status update | normal hourly heartbeat | nothing |
| check failed | the page looked different | send me `vfs_monitor.log` |

---

## If you do only one thing today

Create the Oracle server (Part 1, steps 1–6). If anything on that Oracle screen is
unclear, send me a screenshot of it and I will tell you exactly what to pick.
