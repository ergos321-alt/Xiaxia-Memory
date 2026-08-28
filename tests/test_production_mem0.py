"""Credential-gated end-to-end checks against Qwen + Supabase PGVector.

These tests intentionally use the production providers and are skipped unless the
operator explicitly supplies an isolated test database/configuration.
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db import Database
from app.domain_repository import DomainRepository
from app.memory_engine import MemoryEngine


REQUIRED = os.getenv("RUN_PRODUCTION_MEM0_TESTS") == "1" and os.getenv("DATABASE_URL") and os.getenv("QWEN_API_KEY")
pytestmark = pytest.mark.skipif(not REQUIRED, reason="requires RUN_PRODUCTION_MEM0_TESTS=1 plus Qwen/Supabase credentials")


def production_config():
    return {
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "QWEN_API_KEY": os.environ["QWEN_API_KEY"],
        "QWEN_BASE_URL": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "QWEN_CHAT_MODEL": os.getenv("QWEN_CHAT_MODEL", "qwen-flash"),
        "QWEN_EMBEDDING_MODEL": os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4"),
        "EMBEDDING_DIMENSIONS": int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
        "MEM0_COLLECTION": os.getenv("MEM0_COLLECTION", "xiaxia_mem0_memories"),
        "MEM0_USER_ID": os.getenv("MEM0_USER_ID", "xiaxia_shared_life"),
        "MEM0_HISTORY_DB_PATH": os.getenv("MEM0_HISTORY_DB_PATH", "/tmp/xiaxia_mem0_production_test_history.db"),
        "MEM0_DB_POOL_MIN": 1,
        "MEM0_DB_POOL_MAX": 2,
    }


def relationship(text, source, **extra):
    return {"memory_text": text, "category": "relationship", "subtype": "milestone",
        "importance": 10, "occurred_at": datetime.now(timezone.utc).isoformat(), "source": source,
        "metadata": {"integration_test": True}, **extra}


def test_qwen_supabase_mem0_full_lifecycle():
    """Actual Mem0 2.0.19 API, Qwen providers, PGVector and domain ledger."""
    cfg = production_config()
    db = Database(cfg["DATABASE_URL"], 1, 2); db.open()
    service = MemoryEngine(DomainRepository(db), cfg)
    marker = f"xiaxia-e2e-{uuid4()}"
    created_ids = []
    try:
        old = service.add_structured(relationship(f"{marker}：过去重视某种关系语言", marker))
        created_ids.append(old["id"])
        new = service.add_structured(relationship(f"{marker}：后来这种语言自然淡化", marker,
            subtype="relationship_dynamic", supersedes=old["id"]))
        created_ids.append(new["id"])
        assert service.mem0.get(new["id"])["memory"].startswith(marker)
        assert service.repository.get(old["id"])["status"] == "superseded"
        current_ids = {row["id"] for row in service.search(marker, {}, 10)}
        assert new["id"] in current_ids and old["id"] not in current_ids

        inferred = service.add_inferred(f"{marker}。我们共同决定长期保存这段历史，但它不规定未来。", marker)
        assert inferred
        created_ids.extend(row["id"] for row in inferred)

        imported = service.archive_period(marker, [relationship(f"{marker}：旧窗口共同经历被重新捡回", marker)], {"test": True})
        created_ids.extend(row["id"] for row in imported)
        assert any(row["id"] == imported[0]["id"] for row in service.search(marker, {}, 20))

        service.update(new["id"], f"{marker}：Viewer 改写后由 Mem0 重建 embedding", {
            "category": "relationship", "subtype": "relationship_dynamic", "importance": 10,
            "occurred_at": datetime.now(timezone.utc).isoformat(), "source": marker, "status": "active",
        })
        assert service.search(f"{marker} Viewer 改写", {}, 10)
        assert any(service.recent_context(14, 40).values())

        service.delete(new["id"], actor="integration_test")
        created_ids.remove(new["id"])
        assert new["id"] not in {row["id"] for row in service.search(marker, {}, 20)}
        assert service.repository.get(new["id"], include_deleted=True)["status"] == "archived"
    finally:
        for mem0_id in created_ids:
            try: service.delete(mem0_id, actor="integration_test_cleanup")
            except Exception: pass
        try: service.mem0.close()
        except Exception: pass
        try: service.mem0.vector_store.connection_pool.close()
        except Exception: pass
        db.close()
