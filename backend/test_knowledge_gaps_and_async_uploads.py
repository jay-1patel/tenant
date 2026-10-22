"""Tests for Background Async Document Ingestion and In-Dashboard Knowledge Gap Analytics.
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from database import (
    init_db,
    get_db_context,
    save_admin_file,
    list_admin_files,
    update_admin_file_status,
    record_unanswered_query,
    list_unanswered_queries,
    resolve_unanswered_query,
    get_knowledge_gaps_summary,
    add_faq_from_gap,
)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    with get_db_context() as conn:
        conn.execute("DELETE FROM unanswered_queries")
        conn.execute("DELETE FROM admin_files WHERE name LIKE 'test_%'")
        conn.execute("DELETE FROM faq_dataset WHERE source_file = 'Knowledge Gap FAQ'")


class TestKnowledgeGapDatabase:
    def test_record_and_list_unanswered_queries(self):
        # Trivial / short queries are ignored
        assert record_unanswered_query("test_tenant", "") is None
        assert record_unanswered_query("test_tenant", "hi") is None
        assert record_unanswered_query("test_tenant", "menu") is None

        # Meaningful questions are recorded
        gap_id = record_unanswered_query(
            tenant_id="test_tenant",
            query="What is your return policy for international orders?",
            wa_id="919876543210",
            reason="low_confidence",
            confidence_score=0.23,
        )
        assert gap_id is not None

        # Verify throttling (subsequent identical query within 10 min returns the same or throttled)
        second_id = record_unanswered_query(
            tenant_id="test_tenant",
            query="What is your return policy for international orders?",
            wa_id="919876543210",
        )
        assert second_id == gap_id

        gaps = list_unanswered_queries("test_tenant", resolved=False)
        assert len(gaps) == 1
        assert gaps[0]["query"] == "What is your return policy for international orders?"
        assert gaps[0]["reason"] == "low_confidence"
        assert abs(gaps[0]["confidence_score"] - 0.23) < 0.001

    def test_knowledge_gaps_summary(self):
        tenant = "analytics_tenant"
        record_unanswered_query(tenant, "Do you offer gluten-free bread?", wa_id="111")
        record_unanswered_query(tenant, "Where is your retail store?", wa_id="222")

        summary = get_knowledge_gaps_summary(tenant)
        assert summary["total_unresolved"] >= 2
        queries = [q["query"] for q in summary["top_queries"]]
        assert "Do you offer gluten-free bread?" in queries

    def test_resolve_knowledge_gap(self):
        tenant = "resolve_tenant"
        gap_id = record_unanswered_query(tenant, "Can I reschedule my appointment?", wa_id="333")
        assert gap_id is not None

        # Resolve the query
        ok = resolve_unanswered_query(gap_id, tenant_id=tenant, resolved_by="admin_sarah", notes="Answered over phone")
        assert ok is True

        # Should not appear in unresolved list
        unresolved = list_unanswered_queries(tenant, resolved=False)
        assert not any(g["id"] == gap_id for g in unresolved)

        # Should appear in resolved list
        resolved = list_unanswered_queries(tenant, resolved=True)
        found = next((g for g in resolved if g["id"] == gap_id), None)
        assert found is not None
        assert found["resolved"] == 1
        assert found["resolved_by"] == "admin_sarah"
        assert found["resolution_notes"] == "Answered over phone"

    def test_add_faq_from_gap(self):
        tenant = "faq_gen_tenant"
        gap_id = record_unanswered_query(tenant, "Do you deliver to Pune?", wa_id="444")
        assert gap_id is not None

        res = add_faq_from_gap(
            tenant_id=tenant,
            gap_id=gap_id,
            question="Do you deliver to Pune?",
            answer="Yes, we deliver across Pune within 24 to 48 hours.",
            resolved_by="admin_ops",
        )
        assert res["status"] == "ok"

        # Verify gap is marked resolved
        unresolved = list_unanswered_queries(tenant, resolved=False)
        assert not any(g["id"] == gap_id for g in unresolved)

        # Verify Q&A was inserted into faq_dataset
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM faq_dataset WHERE tenant_id = ? AND source_file = 'Knowledge Gap FAQ'",
                (tenant,),
            ).fetchone()
            assert row is not None
            assert "Pune" in row["content"]


class TestAsyncFileUploads:
    def test_save_and_update_admin_file_status(self):
        tenant = "file_status_tenant"
        file_id = save_admin_file(
            name="test_doc.pdf",
            ext="pdf",
            module="faq",
            size=1024,
            tenant_id=tenant,
            status="processing",
            chunks_count=0,
        )
        assert file_id > 0

        files = list_admin_files(tenant)
        match = next((f for f in files if f["name"] == "test_doc.pdf"), None)
        assert match is not None
        assert match["status"] == "processing"

        # Update to ready with chunk count
        ok = update_admin_file_status(
            name="test_doc.pdf",
            status="ready",
            chunks_count=12,
            tenant_id=tenant,
        )
        assert ok is True

        files_after = list_admin_files(tenant)
        match_after = next((f for f in files_after if f["name"] == "test_doc.pdf"), None)
        assert match_after is not None
        assert match_after["status"] == "ready"
        assert match_after["chunks_count"] == 12

