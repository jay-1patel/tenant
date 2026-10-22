import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Ensure backend is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from faq.service import (
    _detect_destination,
    _is_conflicting_dest_chunk,
    KNOWN_DESTINATIONS,
)
from database import get_recent_history


class TestDestinationIsolationAndRAG(unittest.TestCase):
    def test_detect_destination(self):
        self.assertEqual(_detect_destination("In my Gujarat package Which hotel ????"), "gujarat")
        self.assertEqual(_detect_destination("What are the best places in Goa?"), "goa")
        self.assertEqual(_detect_destination("Tell me about Srinagar and Gulmarg tour"), "kashmir")
        self.assertEqual(_detect_destination("Munnar houseboat package"), "kerala")
        self.assertIsNone(_detect_destination("What is your refund policy?"))

    def test_is_conflicting_dest_chunk(self):
        target = "gujarat"

        # Chunk about Goa
        goa_chunk = "Stay in comfortable 3-star/4-star hotels in domestic Goa ... ₹18,500 includes hotel, breakfast and dinner"
        goa_meta = {"source_file": "faq3.txt"}
        self.assertTrue(
            _is_conflicting_dest_chunk(goa_chunk, goa_meta, target),
            "Goa chunk should conflict when target is Gujarat",
        )

        # Chunk about Gujarat
        gujarat_chunk = "Best of Gujarat 5N/6D covers Ahmedabad, Somnath, Dwarka and Gir."
        gujarat_meta = {"source_file": "02_gujarat_packages.md"}
        self.assertFalse(
            _is_conflicting_dest_chunk(gujarat_chunk, gujarat_meta, target),
            "Gujarat chunk should NOT conflict when target is Gujarat",
        )

        # Generic chunk mentioning no specific competing destination
        policy_chunk = "Cancellation made 15 days prior to travel date receives an 80% refund."
        policy_meta = {"source_file": "policy.md"}
        self.assertFalse(
            _is_conflicting_dest_chunk(policy_chunk, policy_meta, target),
            "General policy chunk should NOT conflict",
        )

        # Chunk mentioning both (e.g. combined brochure) should not be dropped
        multi_chunk = "We offer tours in Gujarat as well as Goa and Kerala."
        multi_meta = {"source_file": "destinations.md"}
        self.assertFalse(
            _is_conflicting_dest_chunk(multi_chunk, multi_meta, target),
            "Chunk mentioning target destination should not conflict",
        )

    def test_route_tag_stripping_in_recent_history(self):
        # Test clean user messages in get_recent_history
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE chat_history (id INTEGER PRIMARY KEY, wa_id TEXT, message TEXT, response TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO chat_history (wa_id, message, response, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("919512777899", "[send2] In my Gujarat package", "Sure, what would you like to know?"),
        )
        conn.execute(
            "INSERT INTO chat_history (wa_id, message, response, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("919512777899", "[webhook] Which hotel ????", "Hotels are assigned based on category."),
        )

        with patch("database.get_db", return_value=conn):
            history = get_recent_history("919512777899", limit=5)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["user"], "Which hotel ????")
            self.assertEqual(history[1]["user"], "In my Gujarat package")


if __name__ == "__main__":
    unittest.main()
