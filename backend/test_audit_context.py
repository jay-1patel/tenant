"""Tests for trustworthy audit request metadata."""

import os
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database


class AuditRequestContextTests(unittest.TestCase):
    def test_untrusted_forwarded_header_is_ignored(self):
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": ""}, clear=False):
            self.assertEqual(database.trusted_client_ip("198.51.100.2", "203.0.113.77"), "198.51.100.2")

    def test_trusted_proxy_uses_first_untrusted_hop(self):
        with patch.dict(os.environ, {"TRUSTED_PROXY_IPS": "10.0.0.0/8"}, clear=False):
            self.assertEqual(
                database.trusted_client_ip("10.1.2.3", "203.0.113.7, 10.4.5.6"),
                "203.0.113.7",
            )

    def test_malformed_peer_is_not_logged(self):
        self.assertIsNone(database.trusted_client_ip("not-an-ip", "203.0.113.7"))


if __name__ == "__main__":
    unittest.main()
