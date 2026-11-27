"""Throwaway experiment (not part of the app): can real Chromium click Export and fetch 403 hosts?

Run from project root:  python3 code/experiments/pw_probe.py [--headed]
Always exits (hard timeout + browser closed in `finally`).
"""
import os
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)
SITE = "https://www.infosys.com/"
URL_403 = "https://www.infosys.com/investors/investorpresentation/ir-presentation.pdf"
headed = "--headed" in sys.argv

# Hard stop: whatever happens, kill the process after 90s so a window can never hang around.
threading.Timer(90, lambda: (print("HARD TIMEOUT - exiting"), os._exit(1))).start()


def save_if_pdf(label, body, ctype):
    ok = body[:5] == b"%PDF-"
    print(f"{label}: {len(body)} bytes, content-type={ctype}, is_pdf={ok}")
    if ok:
        (OUT / "ir.pdf").write_bytes(body)
    return ok


with sync_playwright() as p:
    b = p.chromium.launch(headless=not headed)
    try:
        ctx = b.new_context(storage_state=str(ROOT / "screener_auth.json"), accept_downloads=True)
        ctx.set_default_timeout(15000)
        page = ctx.new_page()

        # A) Screener login + Export to Excel
        page.goto("https://www.screener.in/company/INFY/consolidated/", wait_until="domcontentloaded")
        print("A) logged in, export button:", page.get_by_role("button", name="Export to Excel").count() > 0)
        with page.expect_download() as d:
            page.get_by_role("button", name="Export to Excel").first.click()
        d.value.save_as(OUT / "infy.xlsx")
        print("A) Excel saved:", (OUT / "infy.xlsx").stat().st_size, "bytes")

        # B) visit the company site like a person (lets it set its bot-check cookies), then fetch the PDF
        try:
            page.goto(SITE, wait_until="domcontentloaded")
            print("B) visited", SITE, "| title:", page.title()[:50])
            page.wait_for_timeout(3000)
            r = ctx.request.get(URL_403, headers={"Referer": SITE})
            save_if_pdf("B) fetch after visit", r.body(), r.headers.get("content-type"))
        except Exception as e:
            print("B) failed:", str(e)[:120])

        # C) navigate straight to the PDF; capture either the response body or a download
        pg = ctx.new_page()
        got = {}
        pg.on("download", lambda dl: got.setdefault("dl", dl))
        try:
            resp = pg.goto(URL_403, wait_until="commit")
            print("C) navigation status:", resp.status if resp else None)
            pg.wait_for_timeout(4000)
            if "dl" in got:
                got["dl"].save_as(OUT / "ir.pdf")
                print("C) saved via download event")
            elif resp and resp.ok:
                save_if_pdf("C) response body", resp.body(), resp.headers.get("content-type"))
        except Exception as e:
            print("C) failed:", str(e)[:120], "| title:", pg.title()[:40])
    finally:
        b.close()
        print("browser closed")
