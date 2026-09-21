#!/usr/bin/env python3
"""Send one test message to each configured Telegram chat.

Use this to prove the bot token and chat IDs work before anything else.

Usage:
    python check_telegram.py
"""

import asyncio

import config

TEST_MESSAGE = (
    "<b>VFS Tehran monitor connected</b>\n\n"
    f"Site: {config.SITE_NAME}\n"
    f"Service: {config.APPOINTMENT_TYPE}\n\n"
    "Alerts and status updates will arrive in this chat."
)


async def main() -> int:
    from telegram import Bot

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    targets = {
        'status chat': config.TELEGRAM_STATUS_CHAT_ID,
        'alert chat': config.TELEGRAM_ALERT_CHAT_ID,
    }
    failures = 0
    try:
        for label, chat_id in targets.items():
            if not chat_id:
                print(f'skip: {label} is not configured')
                continue
            try:
                await bot.send_message(chat_id=chat_id, text=TEST_MESSAGE, parse_mode='HTML')
                print(f'ok: message delivered to {label} ({chat_id})')
            except Exception as exc:
                failures += 1
                print(f'failed: {label} ({chat_id}) -> {exc}')
    finally:
        try:
            await bot.close()
        except Exception:
            pass

    if failures:
        print('')
        print('Checks to make: the bot token is correct, and you have pressed /start')
        print('in the chat with your bot (a bot cannot message you first).')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
