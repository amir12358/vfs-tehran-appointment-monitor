import os
from dotenv import load_dotenv

# Configuration file for the VFS Global (Netherlands / Tehran) appointment monitor.
# Fork of the Rotterdam appointment monitor: the scheduling engine, state handling,
# throttling and Telegram plumbing are reused as-is, while everything site-specific
# (URLs, markers, extractor, message wording) lives here and in the "VFS adapter"
# functions of monitor.py.

load_dotenv()

# ==========================================================
# Telegram settings
# ==========================================================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_STATUS_CHAT_ID = os.environ.get('TELEGRAM_STATUS_CHAT_ID', TELEGRAM_CHAT_ID)
TELEGRAM_ALERT_CHAT_ID = os.environ.get('TELEGRAM_ALERT_CHAT_ID', TELEGRAM_CHAT_ID)

# ==========================================================
# Site identity (used in logs and Telegram messages)
# ==========================================================
SITE_NAME = os.environ.get('SITE_NAME', 'VFS Global Netherlands - Tehran')
SITE_SHORT_NAME = os.environ.get('SITE_SHORT_NAME', 'VFS Tehran')
LOCATION = os.environ.get('LOCATION', 'Tehran, Iran')
SERVICE_KEYWORD = os.environ.get('SERVICE_KEYWORD', 'MVV')
APPOINTMENT_TYPE = os.environ.get('APPOINTMENT_TYPE', SERVICE_KEYWORD)

# ==========================================================
# Site sign-in (only used when credentials are configured)
# ==========================================================
# The VFS booking system shows the calendar only to a signed-in account. These values
# belong in .env (gitignored) or in GitHub repository secrets - never in the repo.
VFS_EMAIL = os.environ.get('VFS_EMAIL', '')
VFS_PASSWORD = os.environ.get('VFS_PASSWORD', '')
# The site asks for applicant details before it shows the calendar. Keep these in
# .env / repository secrets as well - never in the repository itself.
VFS_TITLE = os.environ.get('VFS_TITLE', 'MR.')
VFS_GIVEN_NAME = os.environ.get('VFS_GIVEN_NAME', '')
VFS_SURNAME = os.environ.get('VFS_SURNAME', '')
VFS_PHONE = os.environ.get('VFS_PHONE', '')
VFS_AUTHORIZATION_OPTION = os.environ.get('VFS_AUTHORIZATION_OPTION', 'I confirm the above statement')
LOGIN_ENABLED = os.environ.get('LOGIN_ENABLED', 'True').lower() in ('1', 'true', 'yes')
LOGIN_WAIT_SECONDS = int(os.environ.get('LOGIN_WAIT_SECONDS', 12))

# ==========================================================
# URLs
# ==========================================================
# Official NetherlandsWorldwide entry page. It links to the current VFS appointment
# URL, including the session-scoped "P=" token, so the monitor re-discovers the live
# link on every run instead of trusting a hardcoded one that will expire.
VFS_ENTRY_URL = os.environ.get(
    'VFS_ENTRY_URL',
    'https://www.netherlandsworldwide.nl/making-appointment/iran'
)

# Optional hard override. Leave empty to re-discover the link from VFS_ENTRY_URL.
VFS_URL_OVERRIDE = os.environ.get('VFS_URL', '')

BROWSER_USER_AGENT = os.environ.get(
    'BROWSER_USER_AGENT',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# ==========================================================
# Page markers (matched against lowercased body text)
# ==========================================================
# Text meaning "the appointment system says there is nothing available".
NO_APPOINTMENT_MESSAGES = [
    'no appointment',
    'no appointments',
    'no slot available',
    'no slots available',
    'no available appointment',
    'no time slots',
    'no dates available',
    'currently no appointments',
    'not available at this time',
    'no schedule',
]
# Kept for compatibility with helper code that expects a single string.
NO_APPOINTMENT_MESSAGE = NO_APPOINTMENT_MESSAGES[0]

# ==========================================================
# Status values stored in the state file
# ==========================================================
STATUS_AVAILABLE = 'available'
STATUS_NONE = 'none'
STATUS_BLOCKED = 'blocked'
STATUS_CHALLENGE = 'challenge'
STATUS_CAPTCHA = 'captcha'
STATUS_QUEUE = 'queue'
STATUS_LOGIN = 'login_required'
STATUS_ERROR = 'error'

STATUS_LABELS = {
    STATUS_AVAILABLE: 'Appointments look available',
    STATUS_NONE: 'No appointments available',
    STATUS_BLOCKED: 'Blocked by the site (Cloudflare)',
    STATUS_CHALLENGE: 'Cloudflare browser check did not clear',
    STATUS_CAPTCHA: 'Human verification (CAPTCHA) page',
    STATUS_QUEUE: 'Virtual waiting room / queue',
    STATUS_LOGIN: 'Login required',
    STATUS_ERROR: 'Check failed (unexpected page or error)',
}

# Only this status means "go book now".
ACTIONABLE_STATUSES = [STATUS_AVAILABLE]

# ==========================================================
# Check cadence (VFS is far stricter than a municipal site: stay conservative)
# ==========================================================
CHECK_FREQUENCY = int(os.environ.get('CHECK_FREQUENCY', 1800))
MIN_CHECK_INTERVAL_SECONDS = int(os.environ.get('MIN_CHECK_INTERVAL_SECONDS', 1200))
MAX_CHECK_INTERVAL_SECONDS = int(os.environ.get('MAX_CHECK_INTERVAL_SECONDS', 2400))

# ==========================================================
# Browser / network options
# ==========================================================
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', 20))
SELENIUM_TIMEOUT = int(os.environ.get('SELENIUM_TIMEOUT', 30))
SELENIUM_RETRIES = int(os.environ.get('SELENIUM_RETRIES', 2))
# 'chrome' uses the locally installed Google Chrome, which fits the page better than
# the bundled Chromium. Set BROWSER_CHANNEL= (empty) to use bundled Chromium.
BROWSER_CHANNEL = os.environ.get('BROWSER_CHANNEL', 'chrome')
PLAYWRIGHT_HEADLESS = os.environ.get('PLAYWRIGHT_HEADLESS', 'True').lower() in ('1', 'true', 'yes')
# Steps walked on the VFS site before the calendar is read ("|" separated, in order):
#   click:<visible text>   select:<option text>   login   wait:<seconds>
# An empty value keeps the default below. Retune this remotely for a manual run:
#   gh workflow run vfs-monitor.yml -f "flow_steps=click:Make an appointment|select:MVV|click:Continue"
_flow_steps_env = os.environ.get('FLOW_STEPS', '').strip()
_default_flow_steps = 'click:Make an appointment|select:MVV|click:Continue'
FLOW_STEPS = [part.strip() for part in (_flow_steps_env or _default_flow_steps).split('|') if part.strip()]
# How much page text each navigation step writes to the log (for remote diagnosis).
FLOW_LOG_CHARS = int(os.environ.get('FLOW_LOG_CHARS', 600))
# Extra cycles (with a reload) to give the site time to render the calendar.
FLOW_SETTLE_SECONDS = int(os.environ.get('FLOW_SETTLE_SECONDS', 6))

# Optional saved login session (only needed if availability sits behind a login).
PLAYWRIGHT_STORAGE_STATE = os.environ.get('PLAYWRIGHT_STORAGE_STATE', '')
# Optional outbound proxy for the browser, e.g. a country-specific endpoint:
#   BROWSER_PROXY_SERVER=http://host:port  (optionally with user/password)
# Useful if this machine's own IP is refused but another exit point works.
BROWSER_PROXY_SERVER = os.environ.get('BROWSER_PROXY_SERVER', '')
BROWSER_PROXY_USERNAME = os.environ.get('BROWSER_PROXY_USERNAME', '')
BROWSER_PROXY_PASSWORD = os.environ.get('BROWSER_PROXY_PASSWORD', '')
# Persistent browser profile folder. Keeps the Cloudflare clearance cookie between
# runs, which is what makes a server IP survive the "Just a moment..." check.
BROWSER_PROFILE_DIR = os.environ.get('BROWSER_PROFILE_DIR', '')
# Extra seconds to wait after load so slow/queued pages can finish rendering.
POST_LOAD_WAIT_SECONDS = int(os.environ.get('POST_LOAD_WAIT_SECONDS', 8))
# How long to wait for a Cloudflare "Just a moment..." browser check to clear.
CHALLENGE_WAIT_SECONDS = int(os.environ.get('CHALLENGE_WAIT_SECONDS', 30))
NAVIGATION_TIMEOUT_MS = int(os.environ.get('NAVIGATION_TIMEOUT_MS', 60000))
# Extra navigation hops (country/centre/category) can be added in vfs_adapter.advance_flow().
FLOW_ENABLED = os.environ.get('FLOW_ENABLED', 'True').lower() in ('1', 'true', 'yes')

# ==========================================================
# Notifications
# ==========================================================
NOTIFY_THROTTLE_SECONDS = int(os.environ.get('NOTIFY_THROTTLE_SECONDS', 3600))
NOTIFY_ON_DETAIL_CHANGES = os.environ.get('NOTIFY_ON_DETAIL_CHANGES', 'True').lower() in ('1', 'true', 'yes')
STATUS_UPDATE_INTERVAL_SECONDS = int(os.environ.get('STATUS_UPDATE_INTERVAL_SECONDS', 10800))
STATUS_UPDATE_DELAY_AFTER_ALERT_SECONDS = int(os.environ.get('STATUS_UPDATE_DELAY_AFTER_ALERT_SECONDS', 900))
NOTIFY_ON_STATUS_CHANGES = os.environ.get('NOTIFY_ON_STATUS_CHANGES', 'True').lower() in ('1', 'true', 'yes')
# Attach a screenshot to the alert so it can be verified at a glance.
SEND_SCREENSHOT = os.environ.get('SEND_SCREENSHOT', 'True').lower() in ('1', 'true', 'yes')

# ==========================================================
# Application settings
# ==========================================================
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')
LOG_FILE = os.environ.get('LOG_FILE', 'vfs_monitor.log')
STATE_FILE = os.environ.get('STATE_FILE', 'vfs_state.json')
# Must differ from the Rotterdam monitor's lock file so both can run side by side.
LOCK_FILE = os.environ.get('LOCK_FILE', 'vfs_monitor.lock')
SCREENSHOT_DIR = os.environ.get('SCREENSHOT_DIR', 'screenshots')
SCREENSHOT_KEEP = int(os.environ.get('SCREENSHOT_KEEP', 20))
TASK_SCHEDULER_MODE = os.environ.get('TASK_SCHEDULER_MODE', 'False').lower() in ('1', 'true', 'yes')

# Positive signals: date/list UI is present, so something looks bookable.
AVAILABILITY_MARKERS = [
    'select date',
    'choose date',
    'available appointment',
    'available appointments',
    'available slots',
    'appointment date',
    'book appointment',
    'schedule appointment',
    'select an appointment',
]

# Hard Cloudflare block pages: the request itself was refused, waiting is pointless.
# Note: deliberately no 'ray id' here - the soft interstitial also shows a Ray ID.
BLOCKED_MARKERS = [
    'attention required',
    'sorry, you have been blocked',
    'you are unable to access',
]

# Cloudflare's "Just a moment..." browser check. On a server/datacenter IP this is
# what appears instead of a hard block, and it usually clears by itself, so the
# monitor waits for it (CHALLENGE_WAIT_SECONDS) before deciding anything.
CHALLENGE_MARKERS = [
    'just a moment',
    'checking your browser',
    'enable javascript and cookies to continue',
    'cf-chl',
    'verifying you are human',
    'performing security verification',
    'verifies you are not a bot',
    'security service to protect against malicious bots',
    'challenges.cloudflare.com',
]

# Human-verification pages. These are reported, never bypassed.
CAPTCHA_MARKERS = [
    'captcha',
    'recaptcha',
    'hcaptcha',
    "i'm not a robot",
    'please verify',
]

# Virtual waiting room / queueing system.
QUEUE_MARKERS = [
    'waiting room',
    'you are in queue',
    'virtual waiting',
    'your position in the queue',
    'high demand',
]

# Pages that want credentials before showing availability.
LOGIN_MARKERS = [
    'sign in',
    'log in',
    'password',
    'forgot your password',
    'one time password',
]
