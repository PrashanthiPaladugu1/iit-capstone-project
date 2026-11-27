import support  # noqa: F401
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
from requests.cookies import RequestsCookieJar

import refresh_auth
from auth import load_cookies
from models import AuthError
from support import FakeResponse

LOGIN_HTML = ('<form method="post" action="/login/">'
              '<input type="hidden" name="csrfmiddlewaretoken" value="TOK123">'
              '<input type="text" name="username"><input type="password" name="password"></form>')


class FakeSession:
    """Mimics the bits of requests.Session that refresh_auth uses."""

    def __init__(self, login_ok=True, login_html=LOGIN_HTML):
        self.cookies = RequestsCookieJar()
        self.headers = {}
        self.login_ok, self.login_html = login_ok, login_html
        self.posts = []

    def get(self, url, **kw):
        if url.endswith("/login/"):
            self.cookies.set("csrftoken", "CSRFCOOKIE", domain="www.screener.in", path="/")
            return FakeResponse(200, text=self.login_html, url=url)
        return FakeResponse(200, text="home", url=url)

    def post(self, url, data=None, **kw):
        self.posts.append((url, data, kw))
        if self.login_ok:
            self.cookies.set("sessionid", "SESSION-VALUE", domain="www.screener.in", path="/",
                             expires=2000000000)
            return FakeResponse(200, text="home", url="https://www.screener.in/")
        return FakeResponse(200, text="bad credentials", url="https://www.screener.in/login/")


class LoginTests(unittest.TestCase):
    def test_extract_csrf_token(self):
        self.assertEqual(refresh_auth.extract_csrf(LOGIN_HTML), "TOK123")

    def test_extract_csrf_missing_raises(self):
        with self.assertRaises(AuthError):
            refresh_auth.extract_csrf("<html>no form</html>")

    def test_login_posts_credentials_with_csrf_and_referer(self):
        s = FakeSession()
        refresh_auth.login(s, "me@example.com", "s3cret")
        url, data, kw = s.posts[0]
        self.assertEqual(url, "https://www.screener.in/login/")
        self.assertEqual(data["username"], "me@example.com")
        self.assertEqual(data["password"], "s3cret")
        self.assertEqual(data["csrfmiddlewaretoken"], "TOK123")
        self.assertEqual(kw["headers"]["Referer"], "https://www.screener.in/login/")

    def test_login_failure_raises_without_leaking_password(self):
        with self.assertRaises(AuthError) as cm:
            refresh_auth.login(FakeSession(login_ok=False), "me@example.com", "s3cret")
        self.assertNotIn("s3cret", str(cm.exception))


class StorageStateTests(unittest.TestCase):
    def jar(self):
        s = FakeSession()
        refresh_auth.login(s, "u", "p")
        return s.cookies

    def test_state_has_playwright_shape_and_both_cookies(self):
        state = refresh_auth.cookies_to_storage_state(self.jar())
        self.assertEqual(state["origins"], [])
        by_name = {c["name"]: c for c in state["cookies"]}
        self.assertEqual(set(by_name), {"csrftoken", "sessionid"})
        sid = by_name["sessionid"]
        self.assertEqual((sid["value"], sid["domain"], sid["path"]), ("SESSION-VALUE", "www.screener.in", "/"))
        self.assertEqual(sid["expires"], 2000000000)
        self.assertEqual(by_name["csrftoken"]["expires"], -1)   # session cookie

    def test_written_file_is_loadable_by_the_app(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "screener_auth.json"
            refresh_auth.write_auth_file(path, refresh_auth.cookies_to_storage_state(self.jar()))
            names = {c["name"] for c in load_cookies(path)}
            self.assertIn("sessionid", names)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_file_is_backed_up_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "screener_auth.json"
            path.write_text('{"old": true}')
            refresh_auth.write_auth_file(path, {"cookies": [], "origins": []})
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text()), {"old": True})
            self.assertEqual(json.loads(path.read_text())["cookies"], [])


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "screener_auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, argv, session, env=None, password="pw"):
        with mock.patch("refresh_auth.requests.Session", return_value=session), \
             mock.patch("refresh_auth.getpass.getpass", return_value=password) as gp, \
             mock.patch.dict("os.environ", env or {}, clear=False):
            code = refresh_auth.main(argv + ["--out", str(self.out)])
        return code, gp

    def test_success_writes_file_exit_0_and_prompts_for_password(self):
        code, gp = self.run_main(["--username", "me@example.com"], FakeSession())
        self.assertEqual(code, 0)
        gp.assert_called_once()
        self.assertIn("sessionid", {c["name"] for c in load_cookies(self.out)})

    def test_password_from_env_skips_prompt(self):
        code, gp = self.run_main(["--username", "me@example.com"], FakeSession(),
                                 env={"SCREENER_PASSWORD": "fromenv"})
        self.assertEqual(code, 0)
        gp.assert_not_called()

    def test_username_from_env(self):
        code, _ = self.run_main([], FakeSession(), env={"SCREENER_USER": "me@example.com"})
        self.assertEqual(code, 0)

    def test_bad_credentials_exit_2_and_existing_file_untouched(self):
        self.out.write_text('{"keep": "me"}')
        code, _ = self.run_main(["--username", "me@example.com"], FakeSession(login_ok=False))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(self.out.read_text()), {"keep": "me"})

    def test_network_error_exit_2(self):
        s = FakeSession()
        s.get = mock.Mock(side_effect=requests.ConnectionError("down"))
        code, _ = self.run_main(["--username", "me@example.com"], s)
        self.assertEqual(code, 2)

    def test_password_is_not_a_command_line_option(self):
        with self.assertRaises(SystemExit):
            refresh_auth.main(["--password", "x"])


if __name__ == "__main__":
    unittest.main()
