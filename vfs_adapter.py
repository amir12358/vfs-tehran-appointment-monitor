#!/usr/bin/env python3
"""
VFS Global (Netherlands / Tehran) site adapter.

Everything that is specific to the VFS appointment site lives in this module, so
the shared engine in monitor.py stays close to its Rotterdam original:

    * discovering the live appointment URL (the "P=" token expires)
    * classifying whatever page comes back (available / none / blocked /
      captcha / queue / login / error)
    * extracting appointment details from the page text
    * building the Telegram messages
    * capturing a screenshot for manual verification

Design rules that matter here:

1. A blocked, captcha, queued, login or unrecognised page is NEVER reported as
   "no appointments". Silence would look like "nothing to book" and hide the
   fact that the monitor is not actually seeing the schedule.
2. Nothing is booked and no captcha is bypassed. The monitor only observes and
   notifies.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

import config

try:  # Playwright is optional so the module can still be imported for tests.
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the environment
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightTimeoutError = Exception


# Fallbacks keep this module importable even if config is trimmed down.
STATUS_AVAILABLE = getattr(config, 'STATUS_AVAILABLE', 'available')
STATUS_NONE = getattr(config, 'STATUS_NONE', 'none')
STATUS_BLOCKED = getattr(config, 'STATUS_BLOCKED', 'blocked')
STATUS_CHALLENGE = getattr(config, 'STATUS_CHALLENGE', 'challenge')
STATUS_CAPTCHA = getattr(config, 'STATUS_CAPTCHA', 'captcha')
STATUS_QUEUE = getattr(config, 'STATUS_QUEUE', 'queue')
STATUS_LOGIN = getattr(config, 'STATUS_LOGIN', 'login_required')
STATUS_ERROR = getattr(config, 'STATUS_ERROR', 'error')

STATUS_LABELS = getattr(config, 'STATUS_LABELS', {})

# Statuses that should never be mistaken for "nothing to book".
ALERT_STATUSES = [STATUS_BLOCKED, STATUS_CHALLENGE, STATUS_CAPTCHA, STATUS_QUEUE, STATUS_LOGIN, STATUS_ERROR]


def status_label(status: str) -> str:
    """Human readable label for a status value."""
    return STATUS_LABELS.get(status, status)


def _hits(text_lower: str, markers) -> List[str]:
    return [marker for marker in markers if marker in text_lower]


def classify_page(body_text: str, http_status: Optional[int] = None) -> Tuple[str, Dict]:
    """Classify a loaded page and return (status, evidence).

    Order matters: a block or human-verification notice wins over everything
    else, and an unrecognised page is an ERROR rather than "no appointments".
    """
    low = (body_text or '').lower()
    evidence: Dict = {}

    blocked = _hits(low, getattr(config, 'BLOCKED_MARKERS', []))
    challenge = _hits(low, getattr(config, 'CHALLENGE_MARKERS', []))

    if blocked:
        evidence['blocked'] = blocked
        return STATUS_BLOCKED, evidence

    if challenge:
        # A soft Cloudflare interstitial can also answer with 403, so the page text
        # decides here; the caller then waits for the check to clear.
        evidence['challenge'] = challenge
        if http_status in (403, 429):
            evidence['challenge'].append(f'http {http_status}')
        return STATUS_CHALLENGE, evidence

    if http_status in (403, 429):
        evidence['blocked'] = [f'http {http_status}']
        return STATUS_BLOCKED, evidence

    captcha = _hits(low, getattr(config, 'CAPTCHA_MARKERS', []))
    if captcha:
        evidence['captcha'] = captcha
        return STATUS_CAPTCHA, evidence

    queue = _hits(low, getattr(config, 'QUEUE_MARKERS', []))
    if queue:
        evidence['queue'] = queue
        return STATUS_QUEUE, evidence

    no_slots = _hits(low, getattr(config, 'NO_APPOINTMENT_MESSAGES', []))
    if no_slots:
        evidence['no_slots'] = no_slots
        return STATUS_NONE, evidence

    login = _hits(low, getattr(config, 'LOGIN_MARKERS', []))
    if login:
        evidence['login'] = login
        return STATUS_LOGIN, evidence

    availability = _hits(low, getattr(config, 'AVAILABILITY_MARKERS', []))
    if availability:
        evidence['availability'] = availability
        return STATUS_AVAILABLE, evidence

    evidence['unknown'] = True
    return STATUS_ERROR, evidence


def extract_appointment_url(html: str) -> Optional[str]:
    """Pull the current VFS appointment link out of the official entry page HTML."""
    if not html:
        return None
    urls = re.findall(r"""https?://[^"'\s<>\\]+""", html)
    candidates = []
    for url in urls:
        clean = url.replace('&amp;', '&')
        if 'vfsvisaonline' in clean.lower() and 'appointment' in clean.lower():
            candidates.append(clean)
    if not candidates:
        for url in urls:
            clean = url.replace('&amp;', '&')
            if 'vfsvisaonline' in clean.lower():
                candidates.append(clean)
    if not candidates:
        return None
    # Prefer the zone that is actually configured, when several links are present.
    return candidates[0]


def discover_appointment_url(logger) -> Optional[str]:
    """Return the live VFS appointment URL.

    Uses VFS_URL when explicitly configured, otherwise re-discovers the link from
    the official entry page (the "P=" token in that link is session scoped).
    """
    override = (getattr(config, 'VFS_URL_OVERRIDE', '') or '').strip()
    if override:
        logger.info(f"Using configured VFS URL override: {override[:120]}")
        return override

    entry_url = getattr(config, 'VFS_ENTRY_URL', '')
    if not entry_url:
        logger.error("Neither VFS_URL nor VFS_ENTRY_URL is configured")
        return None

    headers = {'User-Agent': getattr(config, 'BROWSER_USER_AGENT', 'Mozilla/5.0')}
    try:
        response = requests.get(
            entry_url,
            headers=headers,
            timeout=getattr(config, 'REQUEST_TIMEOUT', 20),
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.error(f"Could not load the official entry page {entry_url}: {exc}")
        return None

    url = extract_appointment_url(response.text)
    if not url:
        logger.error(f"No VFS appointment link found on {entry_url} - page layout may have changed")
        return None
    logger.info(f"Discovered VFS appointment URL: {url[:120]}")
    return url


def _launch_kwargs() -> Dict:
    """Browser launch options. 'chrome' matches the real site better than bundled Chromium."""
    kwargs: Dict = {
        'headless': bool(getattr(config, 'PLAYWRIGHT_HEADLESS', True)),
        'args': [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
        ],
    }
    channel = (getattr(config, 'BROWSER_CHANNEL', '') or '').strip()
    if channel:
        kwargs['channel'] = channel

    proxy_server = (getattr(config, 'BROWSER_PROXY_SERVER', '') or '').strip()
    if proxy_server:
        proxy = {'server': proxy_server}
        username = (getattr(config, 'BROWSER_PROXY_USERNAME', '') or '').strip()
        password = (getattr(config, 'BROWSER_PROXY_PASSWORD', '') or '').strip()
        if username:
            proxy['username'] = username
        if password:
            proxy['password'] = password
        kwargs['proxy'] = proxy

    return kwargs


def _context_kwargs() -> Dict:
    """Browser context options, including an optional saved login session."""
    kwargs: Dict = {
        'locale': 'en-US',
        'viewport': {'width': 1366, 'height': 900},
        'user_agent': getattr(config, 'BROWSER_USER_AGENT', None),
    }
    storage_state = (getattr(config, 'PLAYWRIGHT_STORAGE_STATE', '') or '').strip()
    if storage_state and os.path.exists(storage_state):
        kwargs['storage_state'] = storage_state
    return kwargs


def _open_context(playwright, logger):
    """Open a browser context, using a persistent profile when one is configured.

    A persistent profile keeps cookies between runs, which is what lets a server IP
    pass the Cloudflare check once and then stay clear on later cycles.

    Returns (browser_or_None, context): with a persistent profile the context owns
    the browser, so there is nothing extra to close.
    """
    launch_kwargs = _launch_kwargs()
    profile_dir = (getattr(config, 'BROWSER_PROFILE_DIR', '') or '').strip()
    if profile_dir:
        path = Path(profile_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Opening browser with persistent profile: {path}")
        context = playwright.chromium.launch_persistent_context(
            str(path), **_context_kwargs(), **launch_kwargs
        )
        return None, context

    browser = playwright.chromium.launch(**launch_kwargs)
    context = browser.new_context(**_context_kwargs())
    return browser, context


def _wait_for_challenge_to_clear(page, logger) -> str:
    """Wait for a Cloudflare "Just a moment..." browser check to clear.

    Server and datacenter IPs are usually challenged (not blocked). These checks
    normally resolve on their own within a few seconds, so wait instead of
    reporting a failure. Returns the page text after waiting.
    """
    budget = max(0, int(getattr(config, 'CHALLENGE_WAIT_SECONDS', 30)))
    markers = getattr(config, 'CHALLENGE_MARKERS', [])

    def current_text() -> str:
        try:
            return page.locator('body').inner_text()
        except Exception:
            return ''

    body_text = current_text()
    waited = 0
    while waited < budget and _hits((body_text or '').lower(), markers):
        logger.info(f"Cloudflare browser check detected; waiting for it to clear ({waited}/{budget}s)")
        page.wait_for_timeout(3000)
        waited += 3
        body_text = current_text()

    if waited:
        if _hits((body_text or '').lower(), markers):
            logger.warning(f"Cloudflare browser check was still present after {waited}s")
        else:
            logger.info(f"Cloudflare browser check cleared after about {waited}s")

    return body_text


def screenshot_dir() -> Path:
    """Absolute path of the folder that holds alert screenshots."""
    folder = Path(getattr(config, 'SCREENSHOT_DIR', 'screenshots'))
    if not folder.is_absolute():
        folder = Path(__file__).resolve().parent / folder
    return folder


def prune_screenshots(folder: Path, logger) -> None:
    """Keep only the newest SCREENSHOT_KEEP images so the folder cannot grow forever."""
    keep = max(1, int(getattr(config, 'SCREENSHOT_KEEP', 20)))
    try:
        shots = sorted(folder.glob('vfs_*.png'), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in shots[keep:]:
            stale.unlink()
    except Exception as exc:
        logger.debug(f"Screenshot cleanup skipped: {exc}")


def capture_screenshot(page, logger) -> Optional[str]:
    """Save a full page screenshot for manual verification and return its path."""
    try:
        folder = screenshot_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"vfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(path), full_page=True)
        prune_screenshots(folder, logger)
        logger.info(f"Screenshot saved: {path}")
        return str(path)
    except Exception as exc:
        logger.warning(f"Could not capture a screenshot: {exc}")
        return None


def log_page_diagnostics(page, logger, label: str = 'diagnostics') -> None:
    """Log what the page really shows, so the markers can be tuned from the log alone."""
    try:
        logger.info(f"[{label}] url={page.url[:160]}")
        logger.info(f"[{label}] title={page.title()!r}")
        controls: List[str] = []
        for selector in ('a', 'button', 'input[type=submit]', 'select'):
            try:
                for element in page.locator(selector).all()[:10]:
                    text = ''
                    try:
                        text = (element.inner_text() or '').strip()
                    except Exception:
                        text = ''
                    if not text:
                        try:
                            text = (element.get_attribute('value') or '').strip()
                        except Exception:
                            text = ''
                    if text:
                        controls.append(text[:40])
            except Exception:
                continue
        if controls:
            logger.info(f"[{label}] visible controls: {controls[:15]}")
        frames = [frame.url[:120] for frame in page.frames]
        if len(frames) > 1:
            logger.info(f"[{label}] frames: {frames}")
        body_text = page.locator('body').inner_text()
        logger.info(f"[{label}] body text (first 1200 chars): {body_text[:1200]!r}")
    except Exception as exc:
        logger.debug(f"Diagnostics unavailable: {exc}")


EMAIL_SELECTORS = (
    'input[type="email"]',
    'input[name*="email" i]', 'input[id*="email" i]',
    'input[name*="login" i]', 'input[id*="login" i]',
    'input[name*="user" i]', 'input[id*="user" i]',
)

PASSWORD_SELECTORS = (
    'input[type="password"]',
    'input[name*="pass" i]', 'input[id*="pass" i]',
)

LOGIN_LINK_SELECTORS = (
    'a:has-text("login")', 'a:has-text("log in")', 'a:has-text("sign in")',
    'button:has-text("login")', 'button:has-text("sign in")',
    'input[value*="login" i]', 'input[value*="sign in" i]',
)

SUBMIT_SELECTORS = (
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("login")', 'button:has-text("sign in")',
    'input[value*="login" i]', 'input[value*="sign in" i]',
)


def _first_visible(page, selectors) -> Optional[str]:
    """Return the first selector that matches something on the page."""
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return selector
        except Exception:
            continue
    return None


def _click_login_link(page, logger) -> bool:
    """Click a 'Login / Sign in' link or button when the page offers one."""
    selector = _first_visible(page, LOGIN_LINK_SELECTORS)
    if not selector:
        return False
    try:
        page.locator(selector).first.click()
        page.wait_for_timeout(3000)
        logger.info(f"Opened the sign-in page ({selector})")
        return True
    except Exception as exc:
        logger.warning(f"Could not open the sign-in page via {selector}: {exc}")
        return False


def _fill_field(page, selectors, value, logger, label) -> bool:
    """Fill the first matching field. The value itself is never written to the log."""
    selector = _first_visible(page, selectors)
    if not selector:
        return False
    try:
        page.locator(selector).first.fill(value)
        logger.info(f"Filled the {label} field ({selector})")
        return True
    except Exception as exc:
        logger.warning(f"Could not fill the {label} field ({selector}): {exc}")
        return False


def sign_in(page, logger) -> bool:
    """Sign in with the configured account so the calendar becomes visible.

    Every step is guarded: if the page differs from what we expect, we say so in the
    log and let the caller classify whatever is on screen (so a login wall is reported
    as such instead of looking like "no appointments").
    """
    email = (getattr(config, 'VFS_EMAIL', '') or '').strip()
    password = (getattr(config, 'VFS_PASSWORD', '') or '').strip()
    if not (email and password):
        logger.debug("No VFS_EMAIL/VFS_PASSWORD configured - reading the page as it is")
        return False

    _click_login_link(page, logger)

    if not _fill_field(page, EMAIL_SELECTORS, email, logger, 'email'):
        logger.warning("No email/username field found - is this really the sign-in page?")
        return False
    if not _fill_field(page, PASSWORD_SELECTORS, password, logger, 'password'):
        logger.warning("No password field found - is this really the sign-in page?")
        return False

    submit = _first_visible(page, SUBMIT_SELECTORS)
    if not submit:
        logger.warning("No sign-in button found")
        return False
    try:
        page.locator(submit).first.click()
    except Exception as exc:
        logger.warning(f"Could not press the sign-in button ({submit}): {exc}")
        return False

    page.wait_for_timeout(max(3, int(getattr(config, 'LOGIN_WAIT_SECONDS', 12))) * 1000)
    logger.info("Sign-in form submitted")
    return True


def _click_text(page, logger, text: str) -> bool:
    """Click the first link/button whose visible text matches `text`."""
    candidates = (
        f'a:has-text("{text}")',
        f'button:has-text("{text}")',
        f'input[value="{text}"]',
        f'input[value*="{text}" i]',
        f'text="{text}"',
    )
    selector = _first_visible(page, candidates)
    if not selector:
        logger.warning(f"Step not found on this page: '{text}'")
        return False
    try:
        page.locator(selector).first.click()
        page.wait_for_timeout(max(1, int(getattr(config, 'FLOW_SETTLE_SECONDS', 6))) * 1000)
        logger.info(f"Clicked '{text}' ({selector})")
        return True
    except Exception as exc:
        logger.warning(f"Could not click '{text}' ({selector}): {exc}")
        return False


def _log_page_summary(page, logger, label: str) -> None:
    """Log a short description of the current page so the next step can be planned."""
    try:
        controls = []
        for selector in ('a', 'button', 'input[type=submit]', 'input[type=text]', 'input[type=password]', 'select'):
            try:
                for element in page.locator(selector).all()[:10]:
                    text = ''
                    try:
                        text = (element.inner_text() or '').strip()
                    except Exception:
                        text = ''
                    if not text:
                        try:
                            text = (element.get_attribute('value') or '').strip()
                        except Exception:
                            text = ''
                    if text:
                        controls.append(text[:40])
            except Exception:
                continue
        logger.info(f"[{label}] title={page.title()!r} url={page.url[:120]}")
        logger.info(f"[{label}] controls={controls[:18]}")
        body = page.locator('body').inner_text()
        logger.info(f"[{label}] text={body[:int(getattr(config, 'FLOW_LOG_CHARS', 600))]!r}")
    except Exception as exc:
        logger.debug(f"Could not summarise the page: {exc}")


def advance_flow(page, logger) -> None:
    """Walk the site before the calendar is read: navigation steps, then sign-in.

    The real flow could not be observed from the Netherlands (that address is refused),
    so this is built from the diagnostics each run reports: steps are read from
    config.FLOW_CLICKS and every step logs what the next page looks like. Nothing here
    ever raises - a changed page is logged and the caller classifies what is on screen.
    """
    if not getattr(config, 'LOGIN_ENABLED', True):
        logger.debug("LOGIN_ENABLED is off - reading the page as it is")
        return

    _log_page_summary(page, logger, 'start')

    for step in getattr(config, 'FLOW_CLICKS', []):
        _click_text(page, logger, step)
        _log_page_summary(page, logger, f'after: {step}')

    if getattr(config, 'VFS_EMAIL', '') and getattr(config, 'VFS_PASSWORD', ''):
        sign_in(page, logger)
        _log_page_summary(page, logger, 'after: sign-in')
    else:
        logger.debug("advance_flow: no credentials configured, no sign-in attempted")


def check_availability(url: str, logger) -> Tuple[str, Optional[Dict], Optional[str]]:
    """Load the VFS appointment page and classify what comes back.

    Returns (status, appointment_info, screenshot_path). appointment_info is only
    filled for STATUS_AVAILABLE; the other statuses are reported to Telegram so a
    blocked/queued/login page can never be mistaken for "no appointments".
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright is not installed - cannot check the VFS page")
        return STATUS_ERROR, None, None

    try:
        with sync_playwright() as playwright:
            browser, context = _open_context(playwright, logger)
            page = context.new_page()

            http_status: Optional[int] = None
            try:
                response = page.goto(
                    url,
                    wait_until='domcontentloaded',
                    timeout=int(getattr(config, 'NAVIGATION_TIMEOUT_MS', 60000)),
                )
                if response is not None:
                    http_status = response.status
            except PlaywrightTimeoutError as exc:
                logger.error(f"Timeout while loading the VFS page: {exc}")

            wait_seconds = max(0, int(getattr(config, 'POST_LOAD_WAIT_SECONDS', 8)))
            page.wait_for_timeout(wait_seconds * 1000)

            # Server IPs normally get a Cloudflare check instead of a block; wait it out.
            body_text = _wait_for_challenge_to_clear(page, logger)

            if _hits((body_text or '').lower(), getattr(config, 'CHALLENGE_MARKERS', [])):
                # One reload often lets a Cloudflare managed check finish: by now its
                # JavaScript has run and set the clearance cookie in our profile.
                logger.info("Reloading once to let the Cloudflare check finish")
                try:
                    page.reload(
                        wait_until='domcontentloaded',
                        timeout=int(getattr(config, 'NAVIGATION_TIMEOUT_MS', 60000)),
                    )
                    page.wait_for_timeout(max(0, int(getattr(config, 'POST_LOAD_WAIT_SECONDS', 8))) * 1000)
                    body_text = _wait_for_challenge_to_clear(page, logger)
                except Exception as exc:
                    logger.warning(f"Reload after the browser check failed: {exc}")

            if getattr(config, 'FLOW_ENABLED', True):
                try:
                    advance_flow(page, logger)
                except Exception as exc:
                    logger.warning(f"advance_flow failed, continuing with the current page: {exc}")
                body_text = page.locator('body').inner_text()
            status, evidence = classify_page(body_text, http_status)
            logger.info(f"VFS page classified as '{status}' (evidence: {evidence})")

            screenshot_path = None
            if status == STATUS_AVAILABLE and getattr(config, 'SEND_SCREENSHOT', True):
                screenshot_path = capture_screenshot(page, logger)

            if status != STATUS_NONE or getattr(config, 'DEBUG', False):
                log_page_diagnostics(page, logger, label=status)

            info: Optional[Dict] = None
            if status == STATUS_AVAILABLE:
                details = extract_appointment_details(body_text)
                logger.info(f"Extracted appointment details: {details.get('text')}")
                info = {
                    'available': True,
                    'location': getattr(config, 'LOCATION', ''),
                    'service': getattr(config, 'APPOINTMENT_TYPE', ''),
                    'found_at': datetime.now().isoformat(),
                    'url': url,
                    'http_status': http_status,
                    'method': 'playwright_vfs_flow',
                    'appointment_details': details,
                    'appointment_details_text': details.get('text'),
                }

            try:
                context.close()
            except Exception:
                pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

            return status, info, screenshot_path
    except Exception as exc:  # a failed check must never look like "no slots"
        logger.exception(f"Unexpected error while checking the VFS page: {exc}")
        return STATUS_ERROR, None, None


# ==========================================================
# Details extraction
# ==========================================================
MONTH_MAP = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9, 'oct': 10,
    'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}

# Formats the VFS pages can render a date in. The second capture group is an
# optional time so "12 October 2026 09:30" is found as a whole.
DATE_PATTERNS = [
    r'\b(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\b',
    r'\b(\d{1,2}[/.]\d{1,2}[/.]\d{4})(?:\s+(\d{1,2}:\d{2}))?\b',
    r'\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})(?:\s+(\d{1,2}:\d{2}))?\b',
    r'\b([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})(?:\s+(\d{1,2}:\d{2}))?\b',
    r'\b(\d{1,2}\s+[A-Za-z]{3,9})(?:\s+(\d{1,2}:\d{2}))?\b',
]

# Lines containing these words are more likely to describe a bookable slot.
PREFERRED_CONTEXT = ('available', 'select', 'appointment', 'slot', 'date', 'book')


def _manual_parse_datetime(value: str):
    """Fallback parser for the date formats VFS renders (works without dateparser)."""
    from datetime import datetime as _dt

    cleaned = re.sub(r'\s+', ' ', (value or '').strip().replace(',', ' '))

    iso = re.match(r'^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{1,2}):(\d{2}))?$', cleaned)
    if iso:
        year, month, day, hour, minute = iso.groups()
        return _dt(int(year), int(month), int(day), int(hour or 0), int(minute or 0))

    numeric = re.match(r'^(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:\s+(\d{1,2}):(\d{2}))?$', cleaned)
    if numeric:
        day, month, year, hour, minute = numeric.groups()
        return _dt(int(year), int(month), int(day), int(hour or 0), int(minute or 0))

    tokens = cleaned.split(' ')
    try:
        if tokens and tokens[0][:1].isdigit():          # 12 October 2026 [09:30]
            day = int(tokens[0])
            month = MONTH_MAP.get(tokens[1].lower()[:3]) if len(tokens) > 1 else None
            year_token = tokens[2] if len(tokens) > 2 and len(tokens[2]) == 4 and tokens[2][:1].isdigit() else None
            clock = tokens[3] if year_token and len(tokens) > 3 else (tokens[2] if not year_token and len(tokens) > 2 else None)
        else:                                           # October 12, 2026 [09:30]
            month = MONTH_MAP.get(tokens[0].lower()[:3]) if tokens else None
            day = int(tokens[1])
            year_token = tokens[2] if len(tokens) > 2 and len(tokens[2]) == 4 and tokens[2][:1].isdigit() else None
            clock = tokens[3] if year_token and len(tokens) > 3 else (tokens[2] if not year_token and len(tokens) > 2 else None)

        hour = minute = 0
        if clock and ':' in clock:
            hour, minute = (int(part) for part in clock.split(':', 1))
        if month:
            return _dt(int(year_token) if year_token else _dt.now().year, int(month), day, hour, minute)
    except Exception:
        return None
    return None


def _parse_datetime(value: str):
    manual = _manual_parse_datetime(value)
    if manual:
        return manual
    try:
        import dateparser
        return dateparser.parse(value, languages=['en', 'nl'])
    except Exception:
        return None


def extract_appointment_details(page_text: str) -> Dict:
    """Extract appointment/date information from the VFS page text.

    Keeps the same contract as the Rotterdam extractor (raw, text, location,
    datetime_iso) so the shared change detection in monitor.py works unchanged;
    datetime_iso is what makes "the slot time changed" detectable.
    """
    result = {
        'raw': (page_text or '')[:300],
        'text': None,
        'location': getattr(config, 'LOCATION', '') or None,
        'datetime_iso': None,
        'raw_line': None,
    }
    if not page_text:
        result['text'] = 'Details not found - empty page'
        return result

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    candidates = []
    for index, line in enumerate(lines):
        for pattern in DATE_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                continue
            matched_text = re.sub(r'\s+', ' ', match.group(0)).strip()
            parsed = _parse_datetime(matched_text)
            score = 0
            low_line = line.lower()
            if any(keyword in low_line for keyword in PREFERRED_CONTEXT):
                score += 2
            if parsed:
                score += 1
            candidates.append((score, index, matched_text, parsed, line))
            break

    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        _, _, matched_text, parsed, line = candidates[0]
        result['raw_line'] = line[:200]
        if parsed:
            result['datetime_iso'] = parsed.isoformat()
            has_time = bool(re.search(r'\d{1,2}:\d{2}', matched_text))
            result['text'] = parsed.strftime('%d-%m-%Y %H:%M') if has_time else parsed.strftime('%d-%m-%Y')
        else:
            result['text'] = matched_text
        return result

    # No explicit date found: say so honestly instead of inventing one.
    if _hits((page_text or '').lower(), getattr(config, 'AVAILABILITY_MARKERS', [])):
        result['text'] = 'Availability detected, but no date could be parsed - check the site now'
        return result

    result['text'] = 'Details not found - please check website manually'
    return result


# ==========================================================
# Telegram message bodies
# ==========================================================

def build_alert_message(appointment_info: Dict, appointment_details: Optional[str]) -> str:
    """Message sent when the appointment page looks like it has something bookable."""
    info = appointment_info or {}
    details = appointment_details or 'Details not available'
    return f"""
🚨 <b>{config.SITE_SHORT_NAME} appointment possible!</b>

📍 <b>Location:</b> {getattr(config, 'LOCATION', 'Tehran, Iran')}
📋 <b>Service:</b> {info.get('service') or getattr(config, 'APPOINTMENT_TYPE', '')}
⏰ <b>Checked at:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}
🌐 <b>Page:</b> {info.get('url') or getattr(config, 'VFS_ENTRY_URL', '')}
📅 <b>Detected:</b> {details}

<b>Action required:</b>
Open the official appointment page now, verify it yourself and book if it is real.
The attached screenshot shows exactly what the monitor saw.

({info.get('found_at', datetime.now().isoformat())})
"""


def build_status_message(status: str, appointment_details: Optional[str], extra: str = '') -> str:
    """Periodic heartbeat describing the latest known state."""
    details = appointment_details or 'No appointment details available'
    lines = [
        f"<b>{config.SITE_NAME} - status update</b>",
        "",
        f"<b>Status:</b> {status_label(status)}",
        f"<b>Checked at:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        f"<b>Location:</b> {getattr(config, 'LOCATION', 'Tehran, Iran')}",
        f"<b>Service:</b> {getattr(config, 'APPOINTMENT_TYPE', '')}",
        f"<b>Latest details:</b> {details}",
        f"<b>Page:</b> {getattr(config, 'VFS_ENTRY_URL', '')}",
    ]
    if extra:
        lines.append(f"<b>Note:</b> {extra}")
    return "\n".join(lines)


def build_status_alert_message(status: str, previous_status: Optional[str], extra: str = '') -> str:
    """Message sent when the monitor stops seeing the appointment calendar."""
    lines = [
        f"⚠️ <b>{config.SITE_NAME} monitor changed state</b>",
        "",
        f"<b>Status:</b> {status_label(status)}",
        f"<b>Previous:</b> {status_label(previous_status) if previous_status else 'unknown'}",
        f"<b>Checked at:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
    ]
    if extra:
        lines.append(f"<b>Note:</b> {extra}")
    lines.append("")
    lines.append(
        "The monitor is not seeing the appointment calendar right now, so this is NOT "
        "a confirmation that nothing is available."
    )
    return "\n".join(lines)
