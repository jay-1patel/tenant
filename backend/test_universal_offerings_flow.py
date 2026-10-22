import unittest
from unittest.mock import patch, AsyncMock
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services import offerings_flow
import database as db


class UniversalOfferingsFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.wa_id = "919876543210"

    def test_feature_gating_empty_tenant_hides_button(self):
        btn = offerings_flow.get_vertical_offerings_button("non-existent-tenant-xyz")
        self.assertIsNone(btn, "Empty tenant with 0 products must return None")

    def test_vertical_tailored_button_titles(self):
        # Banking tenant
        b_btn = offerings_flow.get_vertical_offerings_button("meridianbank")
        self.assertIsNotNone(b_btn)
        self.assertEqual(b_btn["title"], "🏦 Banking Products")
        self.assertEqual(b_btn["id"], "menu_banking_products")

        # Real Estate tenant
        r_btn = offerings_flow.get_vertical_offerings_button("dlf")
        self.assertIsNotNone(r_btn)
        self.assertEqual(r_btn["title"], "🏢 View Properties")
        self.assertEqual(r_btn["id"], "menu_properties")

        # Tours & Travel tenant
        t_btn = offerings_flow.get_vertical_offerings_button("99destinations")
        self.assertIsNotNone(t_btn)
        self.assertEqual(t_btn["title"], "🎒 Tour Packages")
        self.assertEqual(t_btn["id"], "menu_packages")

        # IT & Software tenant
        it_btn = offerings_flow.get_vertical_offerings_button("leeway-softech")
        self.assertIsNotNone(it_btn)
        self.assertEqual(it_btn["title"], "💻 Our Services")

    @patch("services.offerings_flow._sender")
    async def test_small_catalog_sends_grouped_list_menu(self, mock_sender_factory):
        mock_sender = AsyncMock()
        mock_sender_factory.return_value = mock_sender
        mock_sender.send_list_menu.return_value = True

        # Meridian bank has 3 products (<= 10)
        sent = await offerings_flow.send_offerings_list(self.wa_id, tenant_id="meridianbank")
        self.assertTrue(sent)
        self.assertTrue(mock_sender.send_list_menu.called)

        args, kwargs = mock_sender.send_list_menu.call_args
        sections = args[4]
        # Should have sections for Accounts, Cards, Loans
        sec_titles = [s["title"] for s in sections]
        self.assertIn("Accounts", sec_titles)
        self.assertIn("Cards", sec_titles)
        self.assertIn("Loans", sec_titles)

    @patch("services.offerings_flow._sender")
    async def test_large_catalog_sends_category_selector_first(self, mock_sender_factory):
        mock_sender = AsyncMock()
        mock_sender_factory.return_value = mock_sender
        mock_sender.send_list_menu.return_value = True

        # DLF has 48 products (> 10 rows)
        sent = await offerings_flow.send_offerings_list(self.wa_id, tenant_id="dlf")
        self.assertTrue(sent)
        self.assertTrue(mock_sender.send_list_menu.called)

        args, kwargs = mock_sender.send_list_menu.call_args
        button_text = args[3]
        sections = args[4]
        self.assertEqual(button_text, "Select Category", "Should send Category Selector for >10 items")
        self.assertEqual(sections[0]["title"], "Select Category")
        rows = sections[0]["rows"]
        self.assertTrue(all(r["id"].startswith("cat_") for r in rows))

    @patch("services.offerings_flow._sender")
    async def test_category_selection_sends_filtered_products(self, mock_sender_factory):
        mock_sender = AsyncMock()
        mock_sender_factory.return_value = mock_sender
        mock_sender.send_list_menu.return_value = True

        # Filter DLF by Super Luxury Residential
        sent = await offerings_flow.send_offerings_list(
            self.wa_id, tenant_id="dlf", category="Super Luxury Residential"
        )
        self.assertTrue(sent)
        self.assertTrue(mock_sender.send_list_menu.called)

        args, kwargs = mock_sender.send_list_menu.call_args
        button_text = args[3]
        sections = args[4]
        self.assertEqual(button_text, "View Details")
        self.assertEqual(sections[0]["title"], "Super Luxury Residential")
        rows = sections[0]["rows"]
        self.assertTrue(all(r["id"].startswith("prod_") for r in rows))

    @patch("services.offerings_flow._sender")
    async def test_product_detail_card_and_enquiry_action(self, mock_sender_factory):
        mock_sender = AsyncMock()
        mock_sender_factory.return_value = mock_sender
        mock_sender.send_text_message.return_value = True
        mock_sender.send_button_message.return_value = True

        # Product 6: Meridian Regular Savings Account
        prod = db.get_product(6, tenant_id="meridianbank")
        self.assertIsNotNone(prod)

        sent = await offerings_flow.send_product_details(self.wa_id, prod, tenant_id="meridianbank")
        self.assertTrue(sent)
        self.assertTrue(mock_sender.send_text_message.called)
        self.assertTrue(mock_sender.send_button_message.called)

        # Check button CTA
        btn_args, btn_kwargs = mock_sender.send_button_message.call_args
        buttons = btn_args[2]
        self.assertEqual(buttons[0]["reply"]["id"], "book_prod_6")
        self.assertEqual(buttons[0]["reply"]["title"], "Apply Now")

    @patch("services.offerings_flow._sender")
    async def test_handle_offerings_action_full_dispatch(self, mock_sender_factory):
        mock_sender = AsyncMock()
        mock_sender_factory.return_value = mock_sender
        mock_sender.send_text_message.return_value = True
        mock_sender.send_button_message.return_value = True
        mock_sender.send_list_menu.return_value = True

        # 1. Tap menu_properties
        res1 = await offerings_flow.handle_offerings_action(
            self.wa_id, "View Properties", tenant_id="dlf", pressed_id="menu_properties"
        )
        self.assertIsNotNone(res1)
        self.assertEqual(res1["action"], "offerings_list")

        # 2. Tap a product row
        res2 = await offerings_flow.handle_offerings_action(
            self.wa_id, "The Camellias", tenant_id="dlf", pressed_id="prod_25"
        )
        self.assertIsNotNone(res2)
        self.assertEqual(res2["action"], "product_details")

        # 3. Detailed question about product falls through to FAQ/RAG
        res3 = await offerings_flow.handle_offerings_action(
            self.wa_id, "What is the sqft and possession date of The Camellias?", tenant_id="dlf"
        )
        self.assertIsNone(res3, "Specific question must fall through to FAQ/RAG")


if __name__ == "__main__":
    unittest.main()
