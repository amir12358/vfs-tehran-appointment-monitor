#!/usr/bin/env python3
"""
VFS Global (Netherlands / Tehran) Appointment Monitor
Watches the VFS Global appointment pages for the Netherlands services in Tehran
and sends Telegram notifications (with a screenshot) when slots appear.
"""

import json
import logging
import os
import asyncio
import sys
import argparse
import random
from datetime import datetime
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.blocking import BlockingScheduler
from telegram import Bot
from telegram.error import TelegramError
from logging.handlers import RotatingFileHandler

# Playwright imports (only loaded when needed)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

import config
import vfs_adapter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, config.LOG_FILE)
STATE_FILE_PATH = os.path.join(BASE_DIR, config.STATE_FILE)
LOCK_FILE_PATH = os.path.join(BASE_DIR, config.LOCK_FILE)

# Setup logging
log_level = logging.DEBUG if getattr(config, 'DEBUG', False) else logging.INFO
logger = logging.getLogger(__name__)
logger.setLevel(log_level)

# Rotating file handler to keep logs bounded
if not logger.handlers:
    file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=5*1024*1024, backupCount=5)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

# Optional console logging in debug mode
if getattr(config, 'DEBUG', False) and not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
    stream = logging.StreamHandler()
    stream.setLevel(log_level)
    stream.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream)

# Reduce subprocess logging noise
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('selenium').setLevel(logging.WARNING)


class SingleInstanceGuard:
    """Prevent overlapping monitor runs, which is especially important under Task Scheduler."""

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._handle = None

    def acquire(self) -> bool:
        try:
            import portalocker
            self._handle = open(self.lock_path, 'a+')
            portalocker.lock(self._handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(str(os.getpid()))
            self._handle.flush()
            return True
        except Exception:
            if self._handle:
                try:
                    self._handle.close()
                except Exception:
                    pass
                self._handle = None
            return False

    def release(self) -> None:
        if not self._handle:
            return
        try:
            import portalocker
            portalocker.unlock(self._handle)
        except Exception:
            pass
        try:
            self._handle.close()
        except Exception:
            pass
        self._handle = None

def extract_appointment_details(page_text: str) -> Dict:
    """Delegate to the VFS adapter (kept module level for backwards compatibility)."""
    return vfs_adapter.extract_appointment_details(page_text)

class AppointmentMonitor:
    """Watches the VFS Global appointment site for the Netherlands services in Tehran."""

    def __init__(self):
        # Do not create a long-lived Bot instance; create per-send to avoid closed client issues
        self.status_chat_id = config.TELEGRAM_STATUS_CHAT_ID
        self.alert_chat_id = config.TELEGRAM_ALERT_CHAT_ID
        self.last_state = self._load_state()
        # Use a persistent requests session for connection pooling
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        # Metrics
        self.metrics = {
            'checks_run': 0,
            'notifications_sent': 0,
            'errors': 0
        }

    def close(self) -> None:
        """Release network resources before exiting."""
        try:
            self.session.close()
        except Exception:
            pass

    def _load_state(self) -> Dict:
        """Load last known state from file using a shared lock."""
        try:
            import portalocker
            if os.path.exists(STATE_FILE_PATH):
                with open(STATE_FILE_PATH, 'r+') as f:
                    try:
                        portalocker.lock(f, portalocker.LOCK_SH)
                        f.seek(0)
                        data = json.load(f)
                        portalocker.unlock(f)
                        return data
                    except Exception:
                        try:
                            portalocker.unlock(f)
                        except Exception:
                            pass
        except Exception:
            # Fallback to simple load
            try:
                if os.path.exists(STATE_FILE_PATH):
                    with open(STATE_FILE_PATH, 'r') as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load state file: {e}")

        return {
            "last_check": None, 
            "next_check_not_before": None,
            "appointment_found": False, 
            "last_alert_sent": None,
            "last_notified": None,
            "last_status_update_sent": None,
            "last_appointment_details": None,
            "last_appointment_struct": None,
            "last_notification_reason": None,
            "last_status": None,
            "last_vfs_url": None,
            "last_screenshot": None
        }

    def _get_random_interval_seconds(self) -> int:
        """Return the next randomized check interval within the configured bounds."""
        minimum = max(1, int(getattr(config, 'MIN_CHECK_INTERVAL_SECONDS', 600)))
        maximum = max(minimum, int(getattr(config, 'MAX_CHECK_INTERVAL_SECONDS', 1800)))
        return random.randint(minimum, maximum)

    def _schedule_next_check(self) -> datetime:
        """Persist the next earliest time the monitor should perform a real check."""
        next_run = datetime.now().timestamp() + self._get_random_interval_seconds()
        next_run_dt = datetime.fromtimestamp(next_run)
        self.last_state["next_check_not_before"] = next_run_dt.isoformat()
        return next_run_dt

    def should_run_check_now(self) -> bool:
        """Return True when the randomized interval has elapsed."""
        next_check_iso = self.last_state.get("next_check_not_before")
        if not next_check_iso:
            return True

        try:
            next_check_dt = datetime.fromisoformat(next_check_iso)
        except Exception:
            logger.warning("Stored next-check timestamp is invalid; running immediately and resetting it.")
            return True

        if datetime.now() >= next_check_dt:
            return True

        remaining_seconds = int((next_check_dt - datetime.now()).total_seconds())
        logger.info(f"Skipping check; next randomized run window opens in about {remaining_seconds} seconds.")
        return False

    def _should_send_status_update(self) -> bool:
        """Return True when the periodic heartbeat status update is due."""
        interval_seconds = max(1, int(getattr(config, 'STATUS_UPDATE_INTERVAL_SECONDS', 21600)))
        last_status_iso = self.last_state.get("last_status_update_sent")
        if not last_status_iso:
            last_alert_iso = self.last_state.get("last_alert_sent")
            if not last_alert_iso:
                return True
            try:
                last_alert_dt = datetime.fromisoformat(last_alert_iso)
            except Exception:
                logger.warning("Stored alert timestamp is invalid; allowing status update.")
                return True
            delay_seconds = max(0, int(getattr(config, 'STATUS_UPDATE_DELAY_AFTER_ALERT_SECONDS', 900)))
            if (datetime.now() - last_alert_dt).total_seconds() < delay_seconds:
                remaining_seconds = int(delay_seconds - (datetime.now() - last_alert_dt).total_seconds())
                logger.info(f"Deferring status update; live-alert channel keeps a {delay_seconds}-second lead for another {remaining_seconds} seconds.")
                return False
            return True

        try:
            last_status_dt = datetime.fromisoformat(last_status_iso)
        except Exception:
            logger.warning("Stored heartbeat timestamp is invalid; sending a fresh status update.")
            return True

        if (datetime.now() - last_status_dt).total_seconds() < interval_seconds:
            return False

        last_alert_iso = self.last_state.get("last_alert_sent")
        if not last_alert_iso:
            return True

        try:
            last_alert_dt = datetime.fromisoformat(last_alert_iso)
        except Exception:
            logger.warning("Stored alert timestamp is invalid; allowing status update.")
            return True

        delay_seconds = max(0, int(getattr(config, 'STATUS_UPDATE_DELAY_AFTER_ALERT_SECONDS', 900)))
        if (datetime.now() - last_alert_dt).total_seconds() < delay_seconds:
            remaining_seconds = int(delay_seconds - (datetime.now() - last_alert_dt).total_seconds())
            logger.info(f"Deferring status update; live-alert channel keeps a {delay_seconds}-second lead for another {remaining_seconds} seconds.")
            return False

        return True

    def _build_appointment_alert_message(self, appointment_info: Dict, appointment_details: str) -> str:
        """Delegate to the VFS adapter so all message wording lives in one place."""
        return vfs_adapter.build_alert_message(appointment_info, appointment_details)

    def _build_status_update_message(self, status: str, appointment_details: Optional[str]) -> str:
        """Delegate to the VFS adapter so all message wording lives in one place."""
        return vfs_adapter.build_status_message(status, appointment_details)

    def _save_state(self, state: Dict) -> None:
        """Save current state to file with an exclusive lock."""
        try:
            import portalocker
            with open(STATE_FILE_PATH, 'a+', encoding='utf-8') as state_file:
                portalocker.lock(state_file, portalocker.LOCK_EX)
                try:
                    state_file.seek(0)
                    state_file.truncate()
                    json.dump(state, state_file, indent=2)
                    state_file.flush()
                    os.fsync(state_file.fileno())
                finally:
                    portalocker.unlock(state_file)
        except Exception as e:
            logger.exception(f"Could not save state file: {e}")

    def _send_telegram_notification(self, message: str, chat_id: Optional[str] = None) -> bool:
        """Send notification via Telegram."""
        try:
            asyncio.run(self._send_telegram_notification_async(message, chat_id=chat_id))
            logger.info("Telegram notification sent successfully")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return False

    async def _send_telegram_notification_async(self, message: str, chat_id: Optional[str] = None) -> None:
        """Send notification via Telegram (async). Create a short-lived Bot per send to avoid closed-client reuse issues."""
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        try:
            await bot.send_message(
                chat_id=chat_id or self.status_chat_id,
                text=message,
                parse_mode='HTML'
            )
        finally:
            try:
                await bot.close()
            except Exception:
                pass

    def _send_telegram_photo(self, photo_path: str, caption: str = '', chat_id: Optional[str] = None) -> bool:
        """Send a screenshot via Telegram so an alert can be verified at a glance."""
        try:
            asyncio.run(self._send_telegram_photo_async(photo_path, caption, chat_id=chat_id))
            logger.info("Telegram screenshot sent successfully")
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram screenshot: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram screenshot: {e}")
            return False

    async def _send_telegram_photo_async(self, photo_path: str, caption: str = '', chat_id: Optional[str] = None) -> None:
        """Async variant; a short-lived Bot is created per send to avoid reuse issues."""
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        try:
            with open(photo_path, 'rb') as photo_file:
                await bot.send_photo(
                    chat_id=chat_id or self.alert_chat_id,
                    photo=photo_file,
                    caption=caption[:1024] if caption else None,
                    parse_mode='HTML'
                )
        finally:
            try:
                await bot.close()
            except Exception:
                pass

    def check_vfs_entry_page(self) -> Optional[str]:
        """Discover the live VFS appointment URL for this cycle.

        Returns the URL, or None when it cannot be discovered. The caller reports
        that as an error status - never as "no appointments".
        """
        url = vfs_adapter.discover_appointment_url(logger)
        if url:
            self.last_state['last_vfs_url'] = url
        return url

    def check_vfs_appointments(self):
        """Run one full VFS check: discover the URL, load it, classify it.

        Returns (status, appointment_info, screenshot_path).
        """
        url = self.check_vfs_entry_page()
        if not url:
            return getattr(config, 'STATUS_ERROR', 'error'), None, None
        return vfs_adapter.check_availability(url, logger)

    def check_appointment_advanced(self) -> Optional[Dict]:
        """Compatibility wrapper for callers/tests that only want the appointment dict."""
        _, appointment_info, _ = self.check_vfs_appointments()
        return appointment_info


    def run_check(self) -> None:
        """Run a single appointment check cycle for the VFS site."""
        logger.info("=" * 50)
        logger.info(f"Starting appointment check cycle for {config.SITE_NAME}")

        self.last_state["last_check"] = datetime.now().isoformat()

        # One full check: discover the live URL, load the page, classify what it is.
        status, appointment_info, screenshot_path = self.check_vfs_appointments()

        available_status = getattr(config, 'STATUS_AVAILABLE', 'available')
        appointments_available = status == available_status
        previously_available = self.last_state.get("appointment_found", False)
        previous_status = self.last_state.get("last_status")

        if appointment_info:
            current_appointment_struct = appointment_info.get('appointment_details')
            current_appointment_details = (
                appointment_info.get('appointment_details_text')
                or (current_appointment_struct.get('text') if current_appointment_struct else None)
            )
        else:
            current_appointment_struct = None
            current_appointment_details = None

        last_appointment_details = self.last_state.get("last_appointment_details")
        appointment_details_changed = (
            appointments_available
            and current_appointment_details != last_appointment_details
            and current_appointment_details is not None
        )
        try:
            last_struct = self.last_state.get('last_appointment_struct')
            if (
                current_appointment_struct
                and last_struct
                and current_appointment_struct.get('datetime_iso')
                and last_struct.get('datetime_iso')
                and current_appointment_struct.get('datetime_iso') != last_struct.get('datetime_iso')
            ):
                appointment_details_changed = True
        except Exception:
            pass

        should_send_notification = False
        notification_reason = ""
        notification_message = None

        if appointments_available and not previously_available:
            should_send_notification = True
            notification_reason = "New appointment available"
            self.last_state["appointment_found"] = True
            self.last_state["last_appointment_details"] = current_appointment_details
            self.last_state["last_appointment_struct"] = current_appointment_struct
            self.last_state["last_notified"] = datetime.now().isoformat()
        elif appointments_available and appointment_details_changed and getattr(config, 'NOTIFY_ON_DETAIL_CHANGES', False):
            should_send_notification = True
            notification_reason = f"Appointment details changed from '{last_appointment_details}' to '{current_appointment_details}'"
            self.last_state["last_appointment_details"] = current_appointment_details
            self.last_state["last_appointment_struct"] = current_appointment_struct
            self.last_state["last_notified"] = datetime.now().isoformat()
            logger.info(notification_reason)
        elif appointments_available and appointment_details_changed:
            self.last_state["last_appointment_details"] = current_appointment_details
            self.last_state["last_appointment_struct"] = current_appointment_struct
            logger.info(f"Appointments still available - details updated to: {current_appointment_details} (notification suppressed)")
        elif not appointments_available and previously_available:
            self.last_state["appointment_found"] = False
            self.last_state["last_appointment_details"] = None
            self.last_state["last_appointment_struct"] = None
            logger.info("Appointments no longer available")
        elif appointments_available:
            self.last_state["last_appointment_struct"] = current_appointment_struct
            logger.info(f"Appointments still available - details: {current_appointment_details} (no change in details)")
        else:
            logger.info(f"Nothing bookable this cycle (status: {status})")

        # A blocked/captcha/queue/login/unexpected page must be reported: staying
        # silent would look exactly like "nothing available".
        if (
            not should_send_notification
            and status in vfs_adapter.ALERT_STATUSES
            and previous_status != status
            and getattr(config, 'NOTIFY_ON_STATUS_CHANGES', True)
        ):
            should_send_notification = True
            notification_reason = f"Status changed to '{status}'"
            notification_message = vfs_adapter.build_status_alert_message(
                status,
                previous_status,
                extra="See vfs_monitor.log for this cycle's page diagnostics."
            )

        notification_sent_this_cycle = False
        if should_send_notification:
            throttle_seconds = getattr(config, 'NOTIFY_THROTTLE_SECONDS', 3600)
            last_reason = self.last_state.get('last_notification_reason')
            last_notified_iso = self.last_state.get('last_notified')
            send_allowed = True
            if notification_reason and last_reason == notification_reason and last_notified_iso:
                try:
                    last_notified_dt = datetime.fromisoformat(last_notified_iso)
                    if (datetime.now() - last_notified_dt).total_seconds() < throttle_seconds:
                        send_allowed = False
                        logger.info(f"Skipping notification; same reason sent {throttle_seconds} seconds ago")
                except Exception:
                    pass

            if send_allowed:
                details = current_appointment_details or 'Details not available'
                message = notification_message or vfs_adapter.build_alert_message(appointment_info or {}, details)
                sent = False
                if screenshot_path and getattr(config, 'SEND_SCREENSHOT', True):
                    sent = self._send_telegram_photo(screenshot_path, caption=message, chat_id=self.alert_chat_id)
                if not sent:
                    sent = self._send_telegram_notification(message, chat_id=self.alert_chat_id)
                if sent:
                    notification_sent_this_cycle = True
                    logger.info(f"Notification sent! Reason: {notification_reason}")
                    self.metrics['notifications_sent'] += 1
                    self.last_state['last_notification_reason'] = notification_reason
                    self.last_state['last_alert_sent'] = datetime.now().isoformat()
            else:
                logger.info('Notification suppressed due to throttle')

        if self._should_send_status_update() and not notification_sent_this_cycle:
            status_message = vfs_adapter.build_status_message(status, current_appointment_details)
            if self._send_telegram_notification(status_message, chat_id=self.status_chat_id):
                self.metrics['notifications_sent'] += 1
                self.last_state['last_status_update_sent'] = datetime.now().isoformat()
                logger.info("Periodic status update sent")

        self.last_state['last_status'] = status
        self.metrics['checks_run'] += 1
        next_check_dt = self._schedule_next_check()
        self._save_state(self.last_state)
        logger.info(f"Next randomized check not before {next_check_dt.strftime('%d-%m-%Y %H:%M:%S')}")
        logger.info("Check cycle completed")

    def start_scheduler(self) -> None:
        """Start the blocking scheduler for long-running background operation."""
        scheduler = BlockingScheduler()
        
        scheduler.add_job(
            self.run_check,
            'interval',
            seconds=config.CHECK_FREQUENCY,
            id='appointment_check',
            name='Check for appointments',
            max_instances=1,
            coalesce=True
        )
        
        logger.info(f"Scheduler started - checking every {config.CHECK_FREQUENCY} seconds")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down scheduler...")
            scheduler.shutdown()
            logger.info("Appointment monitor stopped")

    def run_once_with_lock(self, force: bool = False) -> int:
        """Run a single cycle with overlap protection and a useful process exit code.

        force=True ignores the randomized interval; used for manual runs and for the
        very first check after a deployment.
        """
        guard = SingleInstanceGuard(LOCK_FILE_PATH)
        if not guard.acquire():
            logger.warning("Another monitor instance is already running; skipping this execution.")
            return 0

        started_at = datetime.now()
        try:
            if not force and not self.should_run_check_now():
                return 0
            self.run_check()
            duration = (datetime.now() - started_at).total_seconds()
            logger.info(f"Single-run execution finished in {duration:.2f} seconds")
            return 0
        except Exception:
            logger.exception("Unhandled error during single-run execution")
            self.metrics['errors'] += 1
            return 1
        finally:
            self.close()
            guard.release()


def main():
    """Main entry point."""
    logger.info(f"{config.SITE_NAME} appointment monitor starting...")

    parser = argparse.ArgumentParser(description="Monitor VFS Netherlands (Tehran) appointment availability.")
    parser.add_argument("--test", action="store_true", help="Run one check and keep normal logging.")
    parser.add_argument("--once", action="store_true", help="Run one check and exit. Best mode for Windows Task Scheduler.")
    parser.add_argument("--force", action="store_true", help="Ignore the randomized interval and run the check now.")
    parser.add_argument("--scheduler", action="store_true", help="Run continuously using APScheduler.")
    parser.add_argument("--task-scheduler", action="store_true", help="Alias for --once with minimal console noise.")
    args = parser.parse_args()
    
    # Validate configuration
    if config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("ERROR: Set TELEGRAM_BOT_TOKEN in .env or the environment")
        logger.error("Get your bot token from @BotFather on Telegram")
        return 1
    
    if not config.TELEGRAM_STATUS_CHAT_ID:
        logger.error("ERROR: Set TELEGRAM_STATUS_CHAT_ID in .env or the environment")
        return 1

    if not config.TELEGRAM_ALERT_CHAT_ID:
        logger.error("ERROR: Set TELEGRAM_ALERT_CHAT_ID in .env or the environment")
        return 1

    run_once = args.once or args.test or args.task_scheduler or config.TASK_SCHEDULER_MODE
    scheduler_mode = args.scheduler and not run_once
    
    # Initialize monitor
    monitor = AppointmentMonitor()
    
    if args.test:
        logger.info("TEST MODE: Running single check and exiting...")
        exit_code = monitor.run_once_with_lock(force=args.force)
        logger.info("Test completed. Check the logs above for results.")
        return exit_code

    if run_once:
        logger.info("RUN ONCE MODE: Starting a single Task Scheduler-friendly check...")
        return monitor.run_once_with_lock(force=args.force)

    if scheduler_mode:
        logger.info("Running initial check...")
        initial_exit = monitor.run_once_with_lock()
        if initial_exit != 0:
            return initial_exit
        monitor.start_scheduler()
        return 0

    logger.info("No mode specified; defaulting to single-run mode. Use --scheduler for continuous execution.")
    return monitor.run_once_with_lock(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
