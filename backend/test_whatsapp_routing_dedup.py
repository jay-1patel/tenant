"""Regression tests for tenant-scoped WhatsApp intents and inbound dedup."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
from backend.services import dedup
from backend.services import incoming_listener
from services import whatsapp_sender
from routing import message as message_router
from routing import webhook as webhook_router


class WhatsAppRoutingDedupTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_careers_uses_explicit_tenant_profile(self):
        tenant_id = "leewaysoftech"
        expected = "Configured careers response"
        with (
            patch.object(message_router, "_is_distributor", return_value=False),
            patch.object(message_router, "_tenant_feature_enabled", return_value=(True, tenant_id)),
            patch("backend.services.service_answers.answer_for_text", return_value=None),
            patch("backend.services.intent_answers.answer_for_text", return_value=expected) as answer,
            patch.object(message_router, "forward_to_bot", new_callable=AsyncMock) as fallback,
        ):
            result = await message_router.process_message(
                "💼 Career", "919512777899", tenant_id=tenant_id
            )

        self.assertEqual(result["answer"], expected)
        self.assertEqual(result["query_type"], "intent")
        answer.assert_called_once_with("919512777899", "💼 Career", tenant_id=tenant_id)
        fallback.assert_not_awaited()

    async def test_faq_forwarding_keeps_explicit_tenant(self):
        expected = {"answer": "tenant FAQ answer"}
        faq_service = ModuleType("backend.faq.service")
        faq_service.handle_faq_query = AsyncMock(return_value=expected)
        with (
            patch("shared.tenancy.gating.guard_result", return_value=None),
            patch.dict(sys.modules, {"backend.faq.service": faq_service}),
        ):
            result = await message_router.forward_to_bot(
                "faq", "question", "919512777899", tenant_id="tenant-a"
            )

        self.assertEqual(result, expected)
        faq_service.handle_faq_query.assert_awaited_once_with({
            "message": "question",
            "wa_id": "919512777899",
            "tenant_id": "tenant-a",
        })

    async def test_careers_button_uses_profile_answer_before_pipeline(self):
        expected = "Configured careers response"
        message = {
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "menu_careers", "title": "Careers"},
            },
        }
        with (
            patch.object(webhook_router, "_is_handover_active", return_value=False),
            patch.object(webhook_router, "_wants_human_agent", return_value=False),
            patch("backend.services.flow_runner.is_running", return_value=False),
            patch.object(webhook_router, "_is_doc_button_reply", return_value=False),
            patch("backend.services.menu_catalog.profile_button_status", return_value=(True, True)),
            patch("backend.services.flow_runner.flow_for_button", return_value=None),
            patch("backend.services.intent_answers.answer_for_button", return_value=expected) as answer,
            patch("routing.database.touch_customer"),
            patch.object(webhook_router, "log_incoming_message", new_callable=AsyncMock),
            patch.object(webhook_router, "log_outgoing_message", new_callable=AsyncMock),
            patch.object(webhook_router, "save_chat"),
            patch.object(webhook_router, "log_webhook"),
            patch.object(webhook_router.config, "SEND2_USERNAME", "test-user"),
            patch.object(webhook_router.config, "SEND2_PASSWORD", "test-password"),
            patch.object(webhook_router, "send_whatsapp_message") as send,
            patch.object(webhook_router, "process_message", new_callable=AsyncMock) as pipeline,
        ):
            await webhook_router._process_and_reply(
                "919512777899", "Test", "Careers", "interactive", message,
                "wamid.career", tenant_id="leewaysoftech",
            )

        answer.assert_called_once_with("919512777899", "menu_careers", "leewaysoftech")
        send.assert_called_once_with("919512777899", expected)
        pipeline.assert_not_awaited()

    async def test_webhook_claims_repeated_meta_message_only_once(self):
        request = SimpleNamespace()
        request.body = AsyncMock(return_value=json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "contacts": [{"wa_id": "919512777899", "profile": {"name": "Test"}}],
                "messages": [{"id": "wamid.duplicate", "type": "text", "text": {"body": "hello"}}],
            }}]}],
        }).encode())
        tasks = SimpleNamespace(add_task=Mock())
        with (
            patch.object(webhook_router, "log_webhook"),
            patch("shared.tenancy.resolver.resolve_tenant_from_payload", return_value="tenant-a"),
            patch.object(webhook_router, "_is_duplicate", side_effect=[False, True]) as claim,
        ):
            first = await webhook_router.receive_webhook(request, tasks)
            second = await webhook_router.receive_webhook(request, tasks)

        self.assertEqual(first["type"], "accepted")
        self.assertEqual(second["type"], "duplicate")
        self.assertEqual(tasks.add_task.call_count, 1)
        self.assertEqual(claim.call_args_list[0].args, ("wamid.duplicate", "919512777899"))

    def test_database_dedup_blocks_repeats_across_local_caches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "dedup.sqlite3")
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                # A second initialization must remain safe and preserve the table.
                database.init_db()
                dedup._l1_cache.clear()

                self.assertFalse(dedup.is_duplicate("wamid.shared", "919512777899"))
                # Simulate a different worker with an empty process-local cache.
                dedup._l1_cache.clear()
                self.assertTrue(dedup.is_duplicate("wamid.shared", "919512777899"))
                self.assertFalse(dedup.is_duplicate("", "919512777899"))

        dedup._l1_cache.clear()

    async def test_listener_processes_each_polled_message_id_once(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: [
                {"messageid": "wamid.poll", "Number": "919512777899", "Message": "Career"},
                {"messageid": "wamid.poll", "Number": "919512777899", "Message": "Career"},
            ],
        )
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        class FakeAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *_args):
                return False
        processed = {"messages": [{"type": "text", "text": "answer"}]}
        stop_event = asyncio.Event()

        async def sleep(_seconds):
            stop_event.set()

        with (
            patch.object(incoming_listener, "SEND2_USERNAME", "username"),
            patch.object(incoming_listener, "SEND2_PASSWORD", "password"),
            patch.object(incoming_listener.httpx, "AsyncClient", FakeAsyncClient),
            patch.object(incoming_listener, "POLL_INTERVAL_SECONDS", 0),
            patch("services.dedup.is_duplicate", side_effect=[False, True]) as claim,
            patch("services.orchestrator.process_incoming_message", new_callable=AsyncMock, return_value=processed) as process,
            patch.object(incoming_listener, "_send_reply", new_callable=AsyncMock) as send_reply,
            patch.object(incoming_listener.asyncio, "sleep", side_effect=sleep),
        ):
            await incoming_listener.poll_incoming_messages(stop_event)

        self.assertEqual(claim.call_count, 2)
        process.assert_awaited_once_with("919512777899", "Career", capture_only=True)
        send_reply.assert_awaited_once_with("919512777899", processed["messages"])

    async def test_orchestrator_capture_only_prevents_listener_double_send(self):
        from services import orchestrator

        class FakeDb:
            @staticmethod
            def execute(query, params=()):
                if query.startswith("SELECT state"):
                    return SimpleNamespace(fetchone=lambda: None)
                if query.startswith("SELECT 1 FROM distributors"):
                    return SimpleNamespace(fetchone=lambda: (1,))
                return SimpleNamespace(fetchone=lambda: None)

        @contextmanager
        def fake_db_context():
            yield FakeDb()

        async def b2b_reply(*_args):
            await whatsapp_sender.send_text_message("919512777899", "one reply")
            return {"status": "processed"}

        with (
            patch.object(orchestrator, "get_db_context", fake_db_context),
            patch("bots.distributor_b2b.workflows.handle_b2b_message", new=b2b_reply),
            patch("kb.services.whatsapp.send_whatsapp_message") as live_send,
        ):
            result = await orchestrator.process_incoming_message(
                "919512777899", "hello", capture_only=True
            )

        self.assertEqual(result["messages"], [{"type": "text", "text": "one reply"}])
        live_send.assert_not_called()

    async def test_capture_only_records_without_live_send(self):
        tokens = whatsapp_sender.begin_capture(capture_only=True)
        try:
            with patch(
                "kb.services.whatsapp.send_whatsapp_message"
            ) as live_send:
                await whatsapp_sender.send_text_message("919512777899", "one reply")
                live_send.assert_not_called()
                self.assertEqual(
                    whatsapp_sender.drain_captured(),
                    [{"type": "text", "text": "one reply"}],
                )
        finally:
            whatsapp_sender.end_capture(tokens)


if __name__ == "__main__":
    unittest.main()
