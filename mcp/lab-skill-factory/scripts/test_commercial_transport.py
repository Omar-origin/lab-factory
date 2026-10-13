#!/usr/bin/env python3
"""Regression coverage for non-browser authorization clients behind Cloudflare."""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import commercial_client as client


class CommercialTransportTests(unittest.TestCase):
    def test_all_license_endpoints_identify_the_application(self):
        for path in ("/api/activate", "/api/lease/refresh", "/api/usage/consume"):
            with self.subTest(path=path):
                def edge(request, *, timeout):
                    # Model the observed edge rejection without sending credentials.
                    if not request.get_header("User-agent", "").startswith("LabFactory/"):
                        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"{}"))
                    self.assertEqual(request.get_method(), "POST")
                    self.assertEqual(request.get_header("Content-type"), "application/json")
                    self.assertEqual(json.loads(request.data), {"probe": True})
                    return io.BytesIO(b'{"ok":true}')

                with patch.object(client.urllib.request, "urlopen", side_effect=edge):
                    self.assertEqual(client.post_json("https://example.test" + path, {"probe": True}), {"ok": True})

    def test_cloudflare_block_is_distinct_from_license_rejection(self):
        body = json.dumps({"cloudflare_error": True, "error_code": 1010, "error_name": "browser_signature_banned"}).encode()
        error = urllib.error.HTTPError("https://example.test/api/activate", 403, "Forbidden", {}, io.BytesIO(body))
        with patch.object(client.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(client.OnlineControlError) as raised:
                client.post_json("https://example.test/api/activate", {})
        self.assertEqual(raised.exception.code, "AUTH_EDGE_BLOCKED")
        self.assertTrue(raised.exception.unavailable)

    def test_application_rejections_keep_their_original_code(self):
        for code, status in (("INVALID_KEY", 404), ("KEY_ALREADY_USED", 409), ("KEY_BANNED", 403)):
            with self.subTest(code=code):
                body = json.dumps({"ok": False, "error": {"code": code, "message": "authorization rejected"}}).encode()
                error = urllib.error.HTTPError("https://example.test/api/activate", status, "Rejected", {}, io.BytesIO(body))
                with patch.object(client.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(client.OnlineControlError) as raised:
                        client.post_json("https://example.test/api/activate", {})
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(raised.exception.unavailable)


if __name__ == "__main__":
    unittest.main()
