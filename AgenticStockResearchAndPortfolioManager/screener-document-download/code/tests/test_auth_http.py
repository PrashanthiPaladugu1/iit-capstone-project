import support  # noqa: F401
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from auth import build_session, load_cookies
from http_client import Fetcher
from models import AuthError


class AuthTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, obj):
        self.path.write_text(json.dumps(obj), encoding="utf-8")

    def test_playwright_storage_state(self):
        self._write({"cookies": [{"name": "sessionid", "value": "abc", "domain": "www.screener.in"},
                                 {"name": "csrftoken", "value": "t"}], "origins": []})
        names = [c["name"] for c in load_cookies(self.path)]
        self.assertEqual(names, ["sessionid", "csrftoken"])

    def test_bare_list_and_flat_dict(self):
        self._write([{"name": "sessionid", "value": "abc"}])
        self.assertEqual(len(load_cookies(self.path)), 1)
        self._write({"sessionid": "abc"})
        self.assertEqual(load_cookies(self.path)[0]["value"], "abc")

    def test_missing_file(self):
        with self.assertRaises(AuthError):
            load_cookies(self.path)

    def test_invalid_json(self):
        self.path.write_text("{oops", encoding="utf-8")
        with self.assertRaises(AuthError):
            load_cookies(self.path)

    def test_missing_sessionid(self):
        self._write({"cookies": [{"name": "csrftoken", "value": "t"}]})
        with self.assertRaises(AuthError):
            load_cookies(self.path)

    def test_session_has_cookie_and_browser_user_agent(self):
        self._write({"cookies": [{"name": "sessionid", "value": "abc", "domain": "www.screener.in",
                                  "path": "/"}]})
        s = build_session(self.path)
        self.assertEqual(s.cookies.get("sessionid", domain="www.screener.in"), "abc")
        self.assertIn("Mozilla/5.0", s.headers["User-Agent"])

    def test_expired_cookie_warns(self):
        self._write({"cookies": [{"name": "sessionid", "value": "abc", "expires": 1.0}]})
        with self.assertLogs("screener_downloader", level="WARNING"):
            build_session(self.path)


class FetcherTests(unittest.TestCase):
    def _fetcher(self, responses, **kw):
        session = mock.Mock()
        session.request.side_effect = responses
        return Fetcher(session, kw.get("min", 0), kw.get("max", 0)), session

    @staticmethod
    def _resp(code):
        r = mock.Mock()
        r.status_code = code
        return r

    def test_returns_success_without_retry(self):
        f, s = self._fetcher([self._resp(200)])
        with mock.patch("http_client.time.sleep"):
            self.assertEqual(f.get("u").status_code, 200)
        self.assertEqual(s.request.call_count, 1)

    def test_non_retryable_status_returned_immediately(self):
        f, s = self._fetcher([self._resp(403)])
        with mock.patch("http_client.time.sleep"):
            self.assertEqual(f.get("u").status_code, 403)
        self.assertEqual(s.request.call_count, 1)

    def test_retries_503_then_succeeds(self):
        f, s = self._fetcher([self._resp(503), self._resp(200)])
        with mock.patch("http_client.time.sleep"):
            self.assertEqual(f.get("u").status_code, 200)
        self.assertEqual(s.request.call_count, 2)

    def test_retries_network_error_then_succeeds(self):
        f, s = self._fetcher([requests.ConnectionError("boom"), self._resp(200)])
        with mock.patch("http_client.time.sleep"):
            self.assertEqual(f.get("u").status_code, 200)

    def test_gives_up_after_max_retries(self):
        f, s = self._fetcher([self._resp(500)] * 3)
        with mock.patch("http_client.time.sleep"):
            with self.assertRaises(requests.RequestException):
                f.get("u")
        self.assertEqual(s.request.call_count, 3)

    def test_polite_delay_within_range(self):
        f, s = self._fetcher([self._resp(200)], min=1.0, max=2.0)
        with mock.patch("http_client.time.sleep") as sleep:
            f.get("u")
        delay = sleep.call_args_list[0].args[0]
        self.assertTrue(1.0 <= delay <= 2.0, delay)

    def test_post_method_is_forwarded(self):
        f, s = self._fetcher([self._resp(200)])
        with mock.patch("http_client.time.sleep"):
            f.request("POST", "u", data={"a": "b"})
        self.assertEqual(s.request.call_args.args[:2], ("POST", "u"))
        self.assertEqual(s.request.call_args.kwargs["data"], {"a": "b"})


if __name__ == "__main__":
    unittest.main()
