#!/usr/bin/env python3
"""
Control test for the VFS Cloudflare block.

Loads several hosts with a real Chrome fingerprint (channel='chrome') to show
whether vfsvisaonline.com is blocked specifically for this machine/network
(IP or ASN reputation) or whether the whole browser stack is being refused.

Usage:
    python recon_control.py
"""

from playwright.sync_api import sync_playwright

URLS = [
    ("cloudflare.com (baseline)", "https://www.cloudflare.com/"),
    ("netherlandsworldwide.nl (control 200 earlier)", "https://www.netherlandsworldwide.nl/making-appointment/iran"),
    ("vfsglobal.com (VFS marketing host)", "https://www.vfsglobal.com/"),
    ("vfsvisaonline.com root", "https://www.vfsvisaonline.com/"),
    (
        "vfsvisaonline Appointment Zone2",
        "https://www.vfsvisaonline.com/Netherlands-Global-Online-Appointment_Zone2/AppScheduling/AppWelcome.aspx",
    ),
]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
        print(f"{'label':<45} {'status':<7} title")
        print("-" * 100)
        for label, url in URLS:
            page = context.new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                status = response.status if response else "n/a"
                page.wait_for_timeout(2500)
                title = page.title()
            except Exception as exc:
                status = "ERR"
                title = f"{type(exc).__name__}: {str(exc)[:60]}"
            print(f"{label:<45} {str(status):<7} {title[:60]}")
            try:
                page.close()
            except Exception:
                pass
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
