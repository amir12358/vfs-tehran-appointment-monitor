"""Classification tests for the VFS adapter.

The most important rule of this monitor: a blocked, queued, login or unknown page
must NEVER be classified as "no appointments", because that would silently look
like "nothing to book" while the monitor is actually blind.
"""

import logging
import unittest

import config
import vfs_adapter


class _override:
    """Temporarily override config values (used for the login tests)."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.original = {name: getattr(config, name, None) for name in self.values}
        for name, value in self.values.items():
            setattr(config, name, value)
        return self

    def __exit__(self, *exc_info):
        for name, value in self.original.items():
            setattr(config, name, value)
        return False


class _FakeLocator:
    """Stand-in for a Playwright locator that matches nothing on the page."""

    def count(self):
        return 0

    @property
    def first(self):
        return self

    def fill(self, value):
        raise AssertionError('fill() must not be called when nothing matches')

    def click(self):
        raise AssertionError('click() must not be called when nothing matches')


class _FakePage:
    """A page on which every selector matches nothing - the worst case for sign-in."""

    def locator(self, selector):
        return _FakeLocator()

    def wait_for_timeout(self, milliseconds):
        pass


class _CapturingLogger:
    """Logger that keeps the messages so a test can assert on them."""

    def __init__(self):
        self.messages = []

    def _record(self, message, *args):
        self.messages.append(str(message))

    info = _record
    debug = _record
    warning = _record
    error = _record


def _test_logger():
    logger = logging.getLogger('vfs_adapter_test')
    logger.addHandler(logging.NullHandler())
    return logger


class TestClassification(unittest.TestCase):
    def test_cloudflare_block(self):
        status, evidence = vfs_adapter.classify_page('Attention Required! | Cloudflare')
        self.assertEqual(status, config.STATUS_BLOCKED)
        self.assertIn('blocked', evidence)

    def test_http_403_is_blocked(self):
        status, evidence = vfs_adapter.classify_page('Some other content', http_status=403)
        self.assertEqual(status, config.STATUS_BLOCKED)
        self.assertIn('http 403', evidence['blocked'])

    def test_cloudflare_block_wins_over_no_slots_text(self):
        page = 'Sorry, you have been blocked. No appointments are available.'
        status, _ = vfs_adapter.classify_page(page)
        self.assertEqual(status, config.STATUS_BLOCKED)

    def test_cloudflare_security_verification_page(self):
        # Observed verbatim on 2026-09-22 while checking the real site: a soft
        # interstitial that is served with HTTP 403. It must be treated as a check
        # to wait out, not as a permanent block.
        page = (
            'www.vfsvisaonline.com\nPerforming security verification\n\n'
            'This website uses a security service to protect against malicious bots. '
            'This page is displayed while the website verifies you are not a bot.\n\n'
            'Ray ID: a3ebcd640d980bde\nPerformance and Security by Cloudflare'
        )
        status, evidence = vfs_adapter.classify_page(page, http_status=403)
        self.assertEqual(status, config.STATUS_CHALLENGE)
        self.assertIn('challenge', evidence)

    def test_cloudflare_challenge_is_its_own_status(self):
        # A soft interstitial (server/datacenter IPs) must NOT be treated as a hard block,
        # because it usually clears by itself and the monitor waits for it.
        status, evidence = vfs_adapter.classify_page(
            'Just a moment... Enable JavaScript and cookies to continue'
        )
        self.assertEqual(status, config.STATUS_CHALLENGE)
        self.assertIn('challenge', evidence)

    def test_http_403_with_challenge_text_stays_a_challenge(self):
        status, _ = vfs_adapter.classify_page('Just a moment...', http_status=403)
        self.assertEqual(status, config.STATUS_CHALLENGE)

    def test_http_403_without_markers_is_blocked(self):
        status, _ = vfs_adapter.classify_page('Some unexpected content', http_status=403)
        self.assertEqual(status, config.STATUS_BLOCKED)

    def test_captcha(self):
        status, _ = vfs_adapter.classify_page('Please complete the CAPTCHA to continue')
        self.assertEqual(status, config.STATUS_CAPTCHA)

    def test_queue(self):
        status, _ = vfs_adapter.classify_page('You are in queue. Please wait.')
        self.assertEqual(status, config.STATUS_QUEUE)

    def test_login_required(self):
        status, _ = vfs_adapter.classify_page('Sign in to continue with your password')
        self.assertEqual(status, config.STATUS_LOGIN)

    def test_no_slots(self):
        status, evidence = vfs_adapter.classify_page('No appointment slots are available at this time')
        self.assertEqual(status, config.STATUS_NONE)
        self.assertIn('no_slots', evidence)

    def test_availability(self):
        status, evidence = vfs_adapter.classify_page('Please select date and book appointment')
        self.assertEqual(status, config.STATUS_AVAILABLE)
        self.assertIn('availability', evidence)

    def test_unknown_page_is_error_not_empty(self):
        status, _ = vfs_adapter.classify_page('Some unexpected page with no markers at all')
        self.assertEqual(status, config.STATUS_ERROR)

    def test_entry_page_url_discovery(self):
        html = (
            '<a href="https://www.vfsvisaonline.com/Netherlands-Global-Online-Appointment_Zone2/'
            'AppScheduling/AppWelcome.aspx?P=abc123">book an appointment</a>'
        )
        url = vfs_adapter.extract_appointment_url(html)
        self.assertIsNotNone(url)
        self.assertIn('AppWelcome.aspx', url)

    def test_entry_page_without_link(self):
        self.assertIsNone(vfs_adapter.extract_appointment_url('<html>no links here</html>'))


class TestLoginFlow(unittest.TestCase):
    """The sign-in path must never crash the check, whatever the page looks like."""

    def test_noop_without_credentials(self):
        with _override(VFS_EMAIL='', VFS_PASSWORD=''):
            vfs_adapter.advance_flow(_FakePage(), _test_logger())  # must not raise

    def test_missing_fields_is_handled(self):
        with _override(VFS_EMAIL='someone@example.com', VFS_PASSWORD='secret'):
            vfs_adapter.advance_flow(_FakePage(), _test_logger())  # must not raise

    def test_password_is_never_written_to_the_log(self):
        logger = _CapturingLogger()
        with _override(VFS_EMAIL='someone@example.com', VFS_PASSWORD='SuperSecret123'):
            vfs_adapter.advance_flow(_FakePage(), logger)
        self.assertNotIn('SuperSecret123', ' '.join(logger.messages))


if __name__ == '__main__':
    unittest.main()
