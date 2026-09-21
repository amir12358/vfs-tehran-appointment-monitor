#!/usr/bin/env python3
"""Preview (and optionally send) the Telegram messages this monitor can produce.

Uses the same message builders as the live monitor, so what you see here is what
you get in production.

Usage:
    python test_appointment_change.py           # print only, no Telegram traffic
    python test_appointment_change.py --send    # deliver the samples to Telegram
"""

import argparse
import asyncio

import config
import vfs_adapter


def build_samples():
    """Return (title, reason, message) for every message type the monitor can send."""
    samples = []

    available_info = {
        'available': True,
        'location': config.LOCATION,
        'service': config.APPOINTMENT_TYPE,
        'url': 'https://www.vfsvisaonline.com/Netherlands-Global-Online-Appointment_Zone2/'
               'AppScheduling/AppWelcome.aspx?P=<your-token>',
        'found_at': 'sample',
        'appointment_details': {'text': '12-10-2026 09:30', 'datetime_iso': '2026-10-12T09:30:00'},
        'appointment_details_text': '12-10-2026 09:30',
    }
    samples.append((
        'Appointments look available',
        'New appointment available',
        vfs_adapter.build_alert_message(available_info, '12-10-2026 09:30'),
    ))
    samples.append((
        'Details changed (same slot moved)',
        'Appointment details changed',
        vfs_adapter.build_alert_message(available_info, '13-10-2026 10:00'),
    ))
    samples.append((
        'Blocked by the site',
        'Status changed to blocked',
        vfs_adapter.build_status_alert_message(config.STATUS_BLOCKED, config.STATUS_NONE),
    ))
    samples.append((
        'Login required',
        'Status changed to login_required',
        vfs_adapter.build_status_alert_message(config.STATUS_LOGIN, config.STATUS_QUEUE),
    ))
    samples.append((
        'Heartbeat, nothing available',
        'Periodic status update',
        vfs_adapter.build_status_message(config.STATUS_NONE, None),
    ))
    return samples


async def send_samples(samples):
    from telegram import Bot

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        for title, _reason, message in samples:
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
            print(f'sent: {title}')
    finally:
        await bot.close()


def main():
    parser = argparse.ArgumentParser(description='Preview the VFS monitor messages.')
    parser.add_argument('--send', action='store_true', help='Send the samples to Telegram.')
    args = parser.parse_args()

    samples = build_samples()
    for title, reason, message in samples:
        print('=' * 70)
        print(f'{title}   (reason: {reason})')
        print('=' * 70)
        print(message.strip())
        print()

    if not args.send:
        print('Dry run only - nothing was sent. Re-run with --send to deliver these.')
        return 0

    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print('ERROR: set TELEGRAM_BOT_TOKEN in .env first')
        return 1
    if not config.TELEGRAM_CHAT_ID:
        print('ERROR: set TELEGRAM_CHAT_ID in .env first')
        return 1

    asyncio.run(send_samples(samples))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
