"""Regression tests for WhatsApp list-menu row ids.

WhatsApp rejects a whole list message when two rows carry the same id
("(#131009) Parameter value is not valid ... Duplicated row id"). The ids
are derived from category slugs and product ids, so the menu builders have
to guarantee uniqueness no matter how the catalogue is spelled.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services import offerings_flow


def _product(pid, name, category, price="", short_description=""):
    return {
        "id": pid,
        "name": name,
        "category": category,
        "price": price,
        "short_description": short_description,
        "is_active": 1,
    }


class FakeDb:
    """A catalogue whose categories differ only in capitalisation."""

    def __init__(self, products, categories):
        self._products = products
        self._categories = categories

    def list_products(self, category=None, active_only=True, limit=100, tenant_id=None):
        rows = self._products
        if category:
            wanted = (category or "").strip().casefold()
            rows = [p for p in rows if (p.get("category") or "").strip().casefold() == wanted]
        return list(rows)

    def list_product_categories(self, active_only=True, tenant_id=None):
        return list(self._categories)

    def count_products(self, category=None, active_only=True, tenant_id=None):
        return len(self.list_products(category=category, active_only=active_only, tenant_id=tenant_id))


class ListMenuRowIdTests(unittest.IsolatedAsyncioTestCase):
    def _send(self, products, categories):
        """Run the offerings list builder and return the sections it sent."""
        sender = AsyncMock()
        sender.send_list_menu.return_value = True
        with patch.object(offerings_flow, "_db", lambda: FakeDb(products, categories)), \
             patch.object(offerings_flow, "_sender", lambda: sender):
            sent = __import__("asyncio").get_event_loop().run_until_complete(
                offerings_flow.send_offerings_list("919876543210", tenant_id="t")
            )
        self.assertTrue(sent)
        args, _ = sender.send_list_menu.call_args
        return args[4]

    def test_category_selector_never_repeats_a_row_id(self):
        # "General" and "general" are the same category written two ways.
        # Both slugify to "general", which used to send two rows with the
        # id "cat_general" and WhatsApp rejected the whole message.
        products = [
            _product(1, "Meridian Basic", "general"),
            _product(2, "Meridian Classic", "general"),
            _product(3, "Overview", "General"),
            _product(4, "Savings Account", "Savings"),
        ]
        # More than MAX_LIST_ROWS products so the category selector is used.
        products += [_product(100 + i, f"Filler {i}", "Other") for i in range(10)]
        sections = self._send(products, ["General", "general", "Savings", "Other"])

        ids = [row["id"] for section in sections for row in section["rows"]]
        self.assertEqual(len(ids), len(set(ids)), f"duplicated row ids: {ids}")
        self.assertEqual(len(ids), 3, "one row per category, not one per spelling")

    def test_case_variant_categories_form_one_section(self):
        products = [
            _product(1, "Meridian Basic", "general"),
            _product(2, "Meridian Classic", "general"),
            _product(3, "Overview", "General"),
        ]
        sections = self._send(products, ["General", "general"])

        self.assertEqual(len(sections), 1, "one section per category")
        ids = [row["id"] for section in sections for row in section["rows"]]
        self.assertEqual(len(ids), len(set(ids)), f"duplicated row ids: {ids}")

    def test_product_rows_never_repeat_an_id(self):
        products = [
            _product(1, "Meridian Basic", "general"),
            _product(2, "Meridian Classic", "general"),
            _product(3, "Overview", "General"),
        ]
        sections = self._send(products, ["General"])

        ids = [row["id"] for section in sections for row in section["rows"]]
        self.assertEqual(len(ids), len(set(ids)), f"duplicated row ids: {ids}")

    def test_category_tap_resolves_to_the_canonical_category(self):
        categories = ["General", "Savings"]
        with patch.object(
            offerings_flow, "_db",
            lambda: FakeDb([_product(1, "Meridian Basic", "general")], categories),
        ):
            matched = offerings_flow._unique_categories(categories)
        self.assertEqual(matched, ["General", "Savings"])


class SendGuardTests(unittest.TestCase):
    """The send2.digital sender is the last line of defence."""

    def test_duplicate_row_ids_are_made_unique_before_sending(self):
        import routing.whatsapp as whatsapp

        sent = {}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, json=None, **kwargs):
                sent["payload"] = json
                raise RuntimeError("stop before the network call")

        sections = [{
            "title": "Select Category",
            "rows": [
                {"id": "cat_general", "title": "General", "description": "10 offerings"},
                {"id": "cat_general", "title": "General ", "description": "8 offerings"},
            ],
        }]
        with patch.object(whatsapp, "get_tenant_send2_credentials", lambda tenant_id=None: ("u", "p")), \
             patch.object(whatsapp.httpx, "Client", FakeClient):
            try:
                whatsapp.send_whatsapp_list_menu("919876543210", "h", "b", "Pick", sections)
            except RuntimeError:
                pass

        ids = [row["id"] for section in sent["payload"]["sections"] for row in section["rows"]]
        self.assertEqual(len(ids), len(set(ids)), f"duplicated row ids reached the API: {ids}")


if __name__ == "__main__":
    unittest.main()
