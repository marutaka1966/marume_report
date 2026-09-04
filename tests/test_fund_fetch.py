"""Official fund fetch retries and public cause mapping. No live orders."""

from __future__ import annotations

import io
import json
import socket
import unittest
import urllib.error
from email.message import EmailMessage
from unittest.mock import patch

from v2.fund_fetch import (
    BLOCKED_BY_SOURCE,
    BROWSER_UA,
    HTML_PARSE_ERROR,
    JSON_PARSE_ERROR,
    MAX_ATTEMPTS,
    TIMEOUT,
    TIMEOUT_SEC,
    UNKNOWN_FETCH_ERROR,
    decode_html_bytes,
    fetch_official_bytes,
    fetch_official_json,
    to_public_fetch_cause,
)
from v2.us_closes import CONNECTION_ERROR, HTTP_403, HTTP_429


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid/fund",
        code,
        "blocked",
        EmailMessage(),
        io.BytesIO(),
    )


class OfficialFetchTests(unittest.TestCase):
    def test_sends_browser_headers_and_timeout(self):
        class _Resp:
            def read(self) -> bytes:
                return b"<html></html>"

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with patch("urllib.request.urlopen", return_value=_Resp()) as opener:
            body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                referer="https://example.invalid/page",
                sleep=lambda _sec: None,
            )
        self.assertEqual(body, b"<html></html>")
        self.assertIsNone(error)
        request = opener.call_args[0][0]
        self.assertEqual(opener.call_args.kwargs["timeout"], TIMEOUT_SEC)
        self.assertEqual(request.get_header("User-agent"), BROWSER_UA)
        self.assertIn("text/html", request.get_header("Accept"))
        self.assertEqual(request.get_header("Referer"), "https://example.invalid/page")

    def test_retries_then_maps_http_403_to_blocked(self):
        slept: list[float] = []
        with patch("urllib.request.urlopen", side_effect=_http_error(403)) as opener:
            body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=slept.append,
            )
        self.assertIsNone(body)
        self.assertEqual(error, BLOCKED_BY_SOURCE)
        self.assertEqual(opener.call_count, MAX_ATTEMPTS)
        self.assertEqual(len(slept), MAX_ATTEMPTS - 1)

    def test_timeout_stays_timeout_after_retries(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=lambda _sec: None,
            )
        self.assertIsNone(body)
        self.assertEqual(error, TIMEOUT)

    def test_401_is_blocked_without_retry(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401)) as opener:
            body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=lambda _sec: None,
            )
        self.assertIsNone(body)
        self.assertEqual(error, BLOCKED_BY_SOURCE)
        self.assertEqual(opener.call_count, 1)

    def test_429_retries_then_blocked(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(429)) as opener:
            _body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="application/json",
                sleep=lambda _sec: None,
            )
        self.assertEqual(error, BLOCKED_BY_SOURCE)
        self.assertEqual(opener.call_count, MAX_ATTEMPTS)
        self.assertEqual(to_public_fetch_cause(HTTP_429), BLOCKED_BY_SOURCE)
        self.assertEqual(to_public_fetch_cause(HTTP_403), BLOCKED_BY_SOURCE)

    def test_connection_error_is_classified(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(ConnectionRefusedError()),
        ):
            _body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=lambda _sec: None,
            )
        self.assertEqual(error, CONNECTION_ERROR)

    def test_dns_error_is_classified(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")),
        ):
            _body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=lambda _sec: None,
            )
        self.assertEqual(error, "DNS_ERROR")

    def test_html_and_json_parse_failures(self):
        class Undecodable(bytes):
            def decode(self, encoding="utf-8", errors="strict"):
                raise UnicodeDecodeError(encoding, b"\x00", 0, 1, "no")

        class _NotJson:
            def read(self) -> bytes:
                return b"[1, 2, 3]"

            def __enter__(self) -> "_NotJson":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        text, error = decode_html_bytes(Undecodable(b"x"))
        self.assertIsNone(text)
        self.assertEqual(error, HTML_PARSE_ERROR)
        with patch("urllib.request.urlopen", return_value=_NotJson()):
            payload, error = fetch_official_json(
                "https://example.invalid/api",
                sleep=lambda _sec: None,
            )
        self.assertIsNone(payload)
        self.assertEqual(error, JSON_PARSE_ERROR)

    def test_unknown_error_does_not_include_url(self):
        with patch("urllib.request.urlopen", side_effect=RuntimeError("secret https://example.invalid")):
            _body, error = fetch_official_bytes(
                "https://example.invalid/fund",
                accept="text/html",
                sleep=lambda _sec: None,
            )
        self.assertEqual(error, UNKNOWN_FETCH_ERROR)
        self.assertNotIn("example.invalid", error)
        dumped = json.dumps({"error": error})
        self.assertNotIn("example.invalid", dumped)


if __name__ == "__main__":
    unittest.main()
