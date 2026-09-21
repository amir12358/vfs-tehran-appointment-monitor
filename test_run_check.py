"""Engine tests for run_check with the VFS page check replaced by scripted results."""

import os
import uuid
from datetime import datetime, timedelta

import config
import monitor
from monitor import AppointmentMonitor


class DummyMonitor(AppointmentMonitor):
    """Monitor whose VFS check is scripted, so the engine logic can be tested offline."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent_messages = []
        self.scripted = [
            self.available('12-10-2026 09:30', '2026-10-12T09:30:00'),
            self.available('13-10-2026 10:00', '2026-10-13T10:00:00'),
            (config.STATUS_NONE, None, None),
        ]

    @staticmethod
    def available(text, iso):
        return (config.STATUS_AVAILABLE, {
            'available': True,
            'location': config.LOCATION,
            'service': config.APPOINTMENT_TYPE,
            'found_at': 'test',
            'url': config.VFS_ENTRY_URL,
            'appointment_details': {'text': text, 'datetime_iso': iso},
            'appointment_details_text': text,
        }, None)

    def check_vfs_appointments(self):
        if self.scripted:
            return self.scripted.pop(0)
        return (config.STATUS_NONE, None, None)

    def _send_telegram_notification(self, message, chat_id=None):
        self.sent_messages.append({'message': message, 'chat_id': chat_id})
        return True

    def _send_telegram_photo(self, photo_path, caption='', chat_id=None):
        self.sent_messages.append({'message': caption, 'chat_id': chat_id, 'photo': photo_path})
        return True


class _StateFile:
    """Give each test its own isolated state file."""

    def __enter__(self):
        self.path = os.path.join(os.getcwd(), f'test_state_{uuid.uuid4().hex}.json')
        self.original = monitor.STATE_FILE_PATH
        monitor.STATE_FILE_PATH = self.path
        return self

    def __exit__(self, *exc_info):
        monitor.STATE_FILE_PATH = self.original
        if os.path.exists(self.path):
            os.remove(self.path)
        return False


class _Intervals:
    """Temporarily override config values and restore them afterwards."""

    def __init__(self, **overrides):
        self.overrides = overrides

    def __enter__(self):
        self.original = {name: getattr(config, name) for name in self.overrides}
        for name, value in self.overrides.items():
            setattr(config, name, value)
        return self

    def __exit__(self, *exc_info):
        for name, value in self.original.items():
            setattr(config, name, value)
        return False


def test_new_appointment_then_changed_details_then_gone():
    with _StateFile(), _Intervals(MIN_CHECK_INTERVAL_SECONDS=600, MAX_CHECK_INTERVAL_SECONDS=600):
        monitor_instance = DummyMonitor()

        monitor_instance.run_check()
        assert monitor_instance.last_state['appointment_found'] is True
        assert len(monitor_instance.sent_messages) == 1
        assert monitor_instance.sent_messages[0]['chat_id'] == monitor_instance.alert_chat_id
        assert monitor_instance.last_state.get('last_notification_reason') == 'New appointment available'
        assert monitor_instance.last_state.get('next_check_not_before') is not None
        assert monitor_instance.last_state.get('last_status') == config.STATUS_AVAILABLE

        monitor_instance.run_check()
        assert len(monitor_instance.sent_messages) == 2
        assert monitor_instance.sent_messages[1]['chat_id'] == monitor_instance.alert_chat_id
        assert monitor_instance.last_state.get('last_appointment_details') == '13-10-2026 10:00'
        assert 'Appointment details changed' in monitor_instance.last_state.get('last_notification_reason')

        monitor_instance.run_check()
        assert monitor_instance.last_state['appointment_found'] is False
        assert len(monitor_instance.sent_messages) == 2


def test_status_update_only_when_nothing_changes():
    with _StateFile(), _Intervals(
        MIN_CHECK_INTERVAL_SECONDS=600,
        MAX_CHECK_INTERVAL_SECONDS=600,
        STATUS_UPDATE_INTERVAL_SECONDS=21600,
    ):
        monitor_instance = DummyMonitor()
        monitor_instance.last_state['appointment_found'] = True
        monitor_instance.last_state['last_appointment_details'] = '13-10-2026 10:00'
        monitor_instance.last_state['last_appointment_struct'] = {
            'text': '13-10-2026 10:00',
            'datetime_iso': '2026-10-13T10:00:00',
        }
        monitor_instance.last_state['last_status_update_sent'] = (
            datetime.now() - timedelta(hours=7)
        ).isoformat()
        monitor_instance.scripted = [
            monitor_instance.available('13-10-2026 10:00', '2026-10-13T10:00:00')
        ]

        monitor_instance.run_check()

        assert len(monitor_instance.sent_messages) == 1
        assert monitor_instance.sent_messages[0]['chat_id'] == monitor_instance.status_chat_id
        assert config.SITE_NAME in monitor_instance.sent_messages[0]['message']
        assert monitor_instance.last_state.get('last_status_update_sent') is not None


def test_blocked_status_alerts_once():
    with _StateFile(), _Intervals(MIN_CHECK_INTERVAL_SECONDS=600, MAX_CHECK_INTERVAL_SECONDS=600):
        monitor_instance = DummyMonitor()
        monitor_instance.scripted = [(config.STATUS_BLOCKED, None, None)]

        monitor_instance.run_check()
        assert len(monitor_instance.sent_messages) == 1
        assert monitor_instance.sent_messages[0]['chat_id'] == monitor_instance.alert_chat_id
        assert 'blocked' in monitor_instance.sent_messages[0]['message'].lower()
        assert monitor_instance.last_state['last_status'] == config.STATUS_BLOCKED
        assert monitor_instance.last_state['appointment_found'] is False

        monitor_instance.scripted = [(config.STATUS_BLOCKED, None, None)]
        monitor_instance.run_check()
        assert len(monitor_instance.sent_messages) == 1


def test_error_status_never_looks_like_no_appointments():
    with _StateFile(), _Intervals(MIN_CHECK_INTERVAL_SECONDS=600, MAX_CHECK_INTERVAL_SECONDS=600):
        monitor_instance = DummyMonitor()
        monitor_instance.scripted = [(config.STATUS_ERROR, None, None)]

        monitor_instance.run_check()

        assert monitor_instance.last_state['last_status'] == config.STATUS_ERROR
        assert monitor_instance.last_state['appointment_found'] is False
        assert len(monitor_instance.sent_messages) == 1
        assert 'NOT' in monitor_instance.sent_messages[0]['message']


def test_status_update_waits_15_minutes_after_live_alert():
    with _StateFile(), _Intervals(
        STATUS_UPDATE_INTERVAL_SECONDS=1,
        STATUS_UPDATE_DELAY_AFTER_ALERT_SECONDS=900,
    ):
        monitor_instance = DummyMonitor()
        monitor_instance.last_state['last_status_update_sent'] = (
            datetime.now() - timedelta(hours=4)
        ).isoformat()
        monitor_instance.last_state['last_alert_sent'] = (
            datetime.now() - timedelta(minutes=5)
        ).isoformat()

        assert monitor_instance._should_send_status_update() is False

