# Refreshing `screener_auth.json`

The downloader logs in to Screener.in with the session cookies stored in `screener_auth.json`.
Refresh that file when:

- you changed your Screener password,
- the downloader exits with code **3** ("session cookie is invalid or expired"), or
- the log says `Redirected to login page`.

`screener_auth.json` is a live login. Never share it, commit it, or put it in a public notebook.

## Quick steps

1. From the project root, run:
   ```
   python3 code/refresh_auth.py --username you@example.com
   ```
2. Type your password when asked. It is hidden and is not saved or logged.
3. Wait for `Saved new session to .../screener_auth.json`.
4. Run the downloader again. Finished files are skipped.

## What the script does

| Step | Detail |
|---|---|
| 1 | Opens `https://www.screener.in/login/` and reads the CSRF token from the login form. |
| 2 | Posts your email, password and the token to `/login/`. |
| 3 | Checks that a `sessionid` cookie came back. If not, it stops with an error. |
| 4 | Writes `screener_auth.json` with the `sessionid` and `csrftoken` cookies (owner-only permissions, `600`). |
| 5 | If a file already existed, keeps it as `screener_auth.json.bak`. |

## Options

| Option | Meaning |
|---|---|
| `-u`, `--username` | Your Screener login email. Without it, the script uses env `SCREENER_USER`, then asks. |
| `-o`, `--out` | Where to write the file. Default: `screener_auth.json` in the project root. |
| env `SCREENER_PASSWORD` | Password for unattended use. If unset, the script asks with hidden input. |

There is deliberately no `--password` option, so your password never ends up in shell history.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | New file written. |
| 2 | Login failed, network error, or missing username or password. An existing `screener_auth.json` is left unchanged. |

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| `Login failed: wrong username/password, or Screener asked for a captcha / extra verification` | Check the password. Log in once in your browser (this clears a captcha), then run the script again. |
| `Could not find the CSRF token on the login page` | Screener changed its login page. Use the browser method below. |
| `Network error while logging in` | Check your internet connection and retry. |
| You sign in with Google | The script only supports email and password. Use the browser method below. |
| Downloader still reports an expired session | Confirm the file was updated (`ls -l screener_auth.json`) and that you ran the downloader from the same project folder. |

## Browser method (Google sign-in, captcha, or page changes)

Log in yourself in a real browser window and save the cookies. This uses Playwright, which the project already used for its probe. I have not tested this snippet end to end.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://www.screener.in/login/")
    input("Log in in the browser window, then press Enter here... ")
    ctx.storage_state(path="screener_auth.json")
    browser.close()
```

Run it from the project root. It writes `screener_auth.json` in the format the downloader reads.

## Colab

Upload the new `screener_auth.json` to the same Drive folder as before, replacing the old file, then re-run the notebook's cells 1, 2 and 4. Keep the file in a private Drive folder.

## Related files

- [`code/refresh_auth.py`](../code/refresh_auth.py): the script.
- [`code/auth.py`](../code/auth.py): how the downloader reads the file.
- [`screener_auth.example.json`](../screener_auth.example.json): the file's structure.
