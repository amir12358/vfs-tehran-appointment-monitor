#!/usr/bin/env bash
# ============================================================================
#  VFS Tehran appointment monitor - setup for an Ubuntu server
#  (Oracle Cloud Always Free, or any Ubuntu 22.04 / 24.04 machine)
#
#  Usage on the server, from inside the project folder:
#      chmod +x deploy/install_server.sh
#      ./deploy/install_server.sh
#
#  It will:
#    1. install Python, Chromium, the virtual screen (xvfb) and Chromium's libraries
#    2. create a private Python environment and install the requirements
#    3. install a systemd timer so a check runs every 10 minutes and survives reboots
#    4. look at the website once and show you the verdict
# ============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PY="$VENV_DIR/bin/python"
SERVICE_NAME="vfs-monitor"
SERVICE_USER="$(id -un)"

echo "== project folder : $PROJECT_DIR"
echo "== linux user     : $SERVICE_USER"

if [[ ! -f "$PROJECT_DIR/monitor.py" ]]; then
    echo "ERROR: monitor.py was not found in $PROJECT_DIR"
    echo "Copy the whole project folder to the server first, then run this script."
    exit 1
fi

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    echo "WARNING: no .env file found - Telegram credentials are missing."
    echo "Copy .env from your own computer before relying on notifications."
fi

echo
echo "== 1/4  installing system packages (this needs sudo) ..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip xvfb

echo
echo "== 2/4  creating the private Python environment ..."
if [[ ! -x "$PY" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$PROJECT_DIR/requirements.txt"
"$PY" -m playwright install --with-deps chromium

echo
echo "== 3/4  installing the scheduled task (systemd) ..."
# xvfb-run gives Chromium a virtual screen. A browser that thinks it has a real
# display is far more likely to pass Cloudflare's check than a headless one.
# Note: systemd's Environment= beats the value in .env (python-dotenv does not
# override variables that are already set).
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=VFS Tehran appointment monitor (one check cycle)
After=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PLAYWRIGHT_HEADLESS=False
ExecStart=/usr/bin/xvfb-run -a ${PY} ${PROJECT_DIR}/monitor.py --once
TimeoutStartSec=900
EOF

sudo tee "/etc/systemd/system/${SERVICE_NAME}.timer" >/dev/null <<EOF
[Unit]
Description=Run the VFS Tehran appointment monitor regularly

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}.timer"

echo
echo "== 4/4  looking at the website once, so you can see the verdict ..."
cd "$PROJECT_DIR"
# First the recon tool: it saves page copies and a report you can send on if
# something looks wrong.
xvfb-run -a "$PY" recon_vfs.py || true

echo
echo "-- now a real cycle, exactly as the schedule will run it --"
echo "-- (this is the authoritative verdict: it uses the persistent browser"
echo "--  profile, waits out a Cloudflare check and reloads once)"
xvfb-run -a "$PY" monitor.py --once || true

cat <<EOF

============================================================================
 DONE.

 Report and page copies: $PROJECT_DIR/recon_out

 Useful commands:
   systemctl list-timers | grep vfs        # is the schedule alive?
   sudo systemctl start vfs-monitor.service  # run one check right now
   journalctl -u vfs-monitor.service -n 50   # what the last check did
   tail -f $PROJECT_DIR/vfs_monitor.log      # live log
   sudo systemctl disable --now vfs-monitor.timer   # stop the schedule
============================================================================
EOF
