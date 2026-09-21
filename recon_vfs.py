#!/usr/bin/env python3
"""
Phase 0 recon for the VFS Global (Netherlands / Tehran) appointment monitor.

Non-interactive: loads the official NetherlandsWorldwide appointment page,
follows the VFS Global booking link, and dumps what a real browser sees
(HTML, screenshot, marker scan, document responses) so the monitor's detection
logic can be built from observed facts instead of guesses.

Usage:
    python recon_vfs.py                    # headless bundled Chromium
    python recon_vfs.py --channel chrome   # locally installed Google Chrome
    python recon_vfs.py --headed           # visible window (Cloudflare sometimes needs it)
    python recon_vfs.py --url "<vfs url>"  # probe one specific URL
    python recon_vfs.py --wait 20          # seconds to wait after load (default 12)
"""

import argparse
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "recon_out"

ENTRY_URL = "https://www.netherlandsworldwide.nl/making-appointment/iran"

# Marker groups used to classify what the page actually is.
MARKERS = {
    "cloudflare_block": [
        "sorry, you have been blocked", "you are unable to access", "attention required",
    ],
    "cloudflare_challenge": [
        "just a moment", "checking your browser", "cf-browser-verification",
        "enable javascript and cookies to continue", "cf-chl", "verifying you are human",
    ],
    "captcha": ["captcha", "recaptcha", "hcaptcha", "turnstile", "verify you are human"],
    "queue": ["waiting room", "you are in queue", "virtual waiting", "please wait", "high demand"],
    "login": ["sign in", "sign-in", "log in", "login", "password", "forgot password", "one time password", "otp"],
    "no_slots": [
        "no appointment", "no appointments", "no slots", "no time slot",
        "no available appointment", "currently no", "no schedule",
        "not available at this time", "no dates available",
    ],
    "availability": [
        "select date", "choose date", "available appointment", "appointment date",
        "available slots", "book appointment", "schedule appointment", "calendar",
    ],
}


def find_vfs_links(html: str):
    urls = re.findall(r"""https?://[^"'\s<>\\]+""", html)
    return sorted({u.replace("&amp;", "&") for u in urls if "vfsvisaonline" in u.lower()})


def scan(text: str):
    low = text.lower()
    return {group: {m: low.count(m) for m in words if m in low} for group, words in MARKERS.items()}


def verdict(matched) -> str:
    if matched.get("cloudflare_block"):
        return "BLOCKED (hard Cloudflare block - this network/IP is refused)"
    if matched.get("cloudflare_challenge"):
        return "CLOUDFLARE CHECK (soft interstitial - the monitor waits for it to clear)"
    if matched["captcha"]:
        return "CAPTCHA"
    if matched["queue"]:
        return "QUEUE / waiting room"
    if matched["login"] and not matched["no_slots"]:
        return "LOGIN page (credentials likely required)"
    if matched["no_slots"]:
        return "NO SLOTS (no-appointment state present)"
    if matched["availability"]:
        return "POSSIBLE AVAILABILITY (date/list UI visible)"
    return "UNKNOWN (inspect the saved HTML)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Recon the VFS Tehran appointment pages.")
    parser.add_argument("--url", default=None, help="Probe this URL instead of the discovered VFS link.")
    parser.add_argument("--channel", default=None, help="Browser channel, e.g. 'chrome'.")
    parser.add_argument("--headed", action="store_true", help="Run with a visible window.")
    parser.add_argument("--wait", type=int, default=20, help="Seconds to wait after page load.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    documents = []

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": not args.headed,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if args.channel:
            launch_kwargs["channel"] = args.channel

        print(f"[*] browser: chromium channel={args.channel or 'bundled'} headless={not args.headed}")
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            locale="en-US",
            timezone_id="Europe/Amsterdam",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.on(
            "response",
            lambda r: documents.append((r.status, r.url))
            if r.request.resource_type == "document"
            else None,
        )

        print(f"[*] entry page: {ENTRY_URL}")
        try:
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except PlaywrightTimeoutError as exc:
            print(f"[!] entry page timeout: {exc}")

        entry_html = page.content()
        links = find_vfs_links(entry_html)
        print(f"[*] VFS links discovered on entry page: {len(links)}")
        for link in links[:10]:
            print(f"    {link[:180]}")

        target = args.url or (links[0] if links else None)
        if not target:
            print("[!] No VFS link found and no --url given. Aborting.")
            browser.close()
            return 1

        print(f"[*] loading VFS URL: {target[:180]}")
        status = "n/a"
        try:
            response = page.goto(target, wait_until="domcontentloaded", timeout=60000)
            status = response.status if response else "n/a"
        except PlaywrightTimeoutError as exc:
            print(f"[!] VFS load timeout: {exc}")

        # Cloudflare JS challenges resolve asynchronously, so give it time.
        page.wait_for_timeout(max(0, args.wait) * 1000)

        print(f"[*] VFS HTTP status: {status}")
        print(f"[*] final URL: {page.url[:180]}")
        print(f"[*] title: {page.title()!r}")
        print(f"[*] frames: {[f.url[:120] for f in page.frames]}")

        body_text = page.locator("body").inner_text()
        matched = scan(body_text)

        html_path = OUT_DIR / f"vfs_{stamp}.html"
        txt_path = OUT_DIR / f"vfs_{stamp}.txt"
        png_path = OUT_DIR / f"vfs_{stamp}.png"
        html_path.write_text(page.content(), encoding="utf-8")
        txt_path.write_text(body_text, encoding="utf-8")
        try:
            page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            print(f"[!] screenshot failed: {exc}")

        print("\n[*] document responses (status, url):")
        for code, url in documents:
            print(f"    {code}  {url[:160]}")

        print("\n[*] marker scan:")
        for group, hits in matched.items():
            print(f"    {group}: {hits if hits else '-'}")

        print(f"\n[*] VERDICT: {verdict(matched)}")
        print("\n[*] body text (first 1500 chars):")
        print("-" * 60)
        print(body_text[:1500])
        print("-" * 60)
        print(f"\n[*] artifacts: {html_path}, {txt_path}, {png_path}")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
