"""Scratch script (not imported by the app): screenshot the running web app with headless Chrome over the DevTools protocol.

    bin/run_py.sh ui_shot.py <out.png> [question]

Chrome is found through the environment variable ARPM_CHROME (default: the macOS Google Chrome app).
With a question, the script types it into the chat box and waits for the answer before the screenshot.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

CHROME = os.environ.get("ARPM_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
URL = os.environ.get("ARPM_URL", "http://127.0.0.1:8502")
PORT = 9333


def main(out: str, question: str = "") -> None:
    profile = tempfile.mkdtemp(prefix="arpm-shot-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                               f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = [t for t in tabs if t["type"] == "page"][0]
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("Chrome did not start")
        with connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            counter = iter(range(1, 1000))

            def call(method, **params):
                n = next(counter)
                ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == n:
                        return msg.get("result", {})

            call("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
            call("Page.navigate", url=URL)
            time.sleep(9)                                           # the app renders after its websocket connects
            click = os.environ.get("ARPM_CLICK", "")
            if click:                                               # open an existing chat by its sidebar label
                js = ("[...document.querySelectorAll('button')].find(b => b.innerText.trim() === %s).click()"
                      % json.dumps(click))
                call("Runtime.evaluate", expression=js)
                time.sleep(5)
            if question:
                js = ("(() => { const t = document.querySelector('[data-testid=\"stChatInputTextArea\"]') || "
                      "document.querySelector('textarea'); const set = Object.getOwnPropertyDescriptor("
                      "HTMLTextAreaElement.prototype, 'value').set; set.call(t, %s); "
                      "t.dispatchEvent(new Event('input', {bubbles: true})); "
                      "setTimeout(() => t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', "
                      "keyCode: 13, which: 13, bubbles: true})), 300); })()") % json.dumps(question)
                call("Runtime.evaluate", expression=js)
                time.sleep(float(os.environ.get("ARPM_WAIT", "75")))
            if os.environ.get("ARPM_TOP"):                          # scroll whichever element holds the conversation
                found = call("Runtime.evaluate", returnByValue=True, expression=(
                    "(() => { const out = []; document.querySelectorAll('*').forEach(e => { if (e.scrollTop > 0) { "
                    "out.push(e.tagName + '[' + (e.getAttribute('data-testid') || e.className) + ']'); "
                    "e.scrollTop = 0; } }); return out.join(' | '); })()"))
                print("scrolled:", found.get("result", {}).get("value", ""))
                time.sleep(1)
            shot = call("Page.captureScreenshot", format="png")
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            text = call("Runtime.evaluate", expression="document.body.innerText.slice(0, 700)")
            print(text.get("result", {}).get("value", ""))
    finally:
        chrome.terminate()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
