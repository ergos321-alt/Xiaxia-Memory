import json
from datetime import datetime


class DomainRepository:
    """Xiaxia relationship/lifecycle control plane. It stores no Memory text or vector."""

    def __init__(self, db): self.db = db

    def create(self, record, event_type="created"):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("""INSERT INTO memory_domain
                (mem0_id,category,subtype,importance,occurred_at,source,status,supersedes,superseded_by,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (
                record["mem0_id"], record["category"], record.get("subtype"), record.get("importance", 5),
                record["occurred_at"], record.get("source", "custom_gpt"), record.get("status", "active"),
                record.get("supersedes"), record.get("superseded_by"), json.dumps(record.get("metadata", {}))))
            row = cur.fetchone(); self._audit(cur, row["mem0_id"], event_type, None, row, record.get("source", "custom_gpt")); return row

    def get(self, mem0_id, include_deleted=False):
        clause = "" if include_deleted else "AND deleted_at IS NULL"
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM memory_domain WHERE mem0_id=%s {clause}", (mem0_id,)); return cur.fetchone()

    def get_many(self, ids, include_deleted=False):
        if not ids: return {}
        clause = "" if include_deleted else "AND deleted_at IS NULL"
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM memory_domain WHERE mem0_id = ANY(%s::uuid[]) {clause}", (list(ids),))
            return {str(row["mem0_id"]): row for row in cur.fetchall()}

    def find_by_import_key(self, import_key):
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT * FROM memory_domain
                WHERE deleted_at IS NULL AND metadata->>'legacy_import_key'=%s LIMIT 1""", (import_key,))
            return cur.fetchone()

    def update(self, mem0_id, changes, before_memory=None, after_memory=None, actor="viewer"):
        allowed = {"category", "subtype", "importance", "occurred_at", "source", "status", "metadata"}
        clean = {key: value for key, value in changes.items() if key in allowed}
        assignments, params = [], []
        for key, value in clean.items(): assignments.append(f"{key}=%s"); params.append(json.dumps(value) if key == "metadata" else value)
        assignments.append("updated_at=now()"); params.append(mem0_id)
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_domain WHERE mem0_id=%s FOR UPDATE", (mem0_id,)); before = cur.fetchone()
            if not before: raise ValueError("domain record not found")
            cur.execute(f"UPDATE memory_domain SET {', '.join(assignments)} WHERE mem0_id=%s RETURNING *", params); after = cur.fetchone()
            self._audit(cur, mem0_id, "updated", {"domain": before, "memory": before_memory}, {"domain": after, "memory": after_memory}, actor); return after

    def supersede(self, old_id, new_id, actor="custom_gpt"):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_domain WHERE mem0_id=%s FOR UPDATE", (old_id,)); before = cur.fetchone()
            if not before: raise ValueError("superseded Memory domain record not found")
            cur.execute("UPDATE memory_domain SET status='superseded',superseded_by=%s,updated_at=now() WHERE mem0_id=%s RETURNING *", (new_id, old_id)); old = cur.fetchone()
            cur.execute("UPDATE memory_domain SET supersedes=%s,updated_at=now() WHERE mem0_id=%s RETURNING *", (old_id, new_id)); new = cur.fetchone()
            self._audit(cur, old_id, "superseded", before, old, actor); self._audit(cur, new_id, "supersedes", None, new, actor); return old, new

    def mark_deleted(self, mem0_id, actor="viewer"):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_domain WHERE mem0_id=%s FOR UPDATE", (mem0_id,)); before = cur.fetchone()
            if not before: raise ValueError("domain record not found")
            cur.execute("UPDATE memory_domain SET status='archived',deleted_at=now(),updated_at=now() WHERE mem0_id=%s RETURNING *", (mem0_id,)); after = cur.fetchone()
            self._audit(cur, mem0_id, "delete_pending", before, after, actor); return before, after

    def rollback_delete(self, before, actor="system"):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("UPDATE memory_domain SET status=%s,deleted_at=%s,updated_at=now() WHERE mem0_id=%s RETURNING *", (before["status"], before["deleted_at"], before["mem0_id"])); after = cur.fetchone()
            self._audit(cur, before["mem0_id"], "delete_rolled_back", None, after, actor)

    def confirm_deleted(self, mem0_id, snapshot, actor="viewer"):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_domain WHERE mem0_id=%s", (mem0_id,)); row = cur.fetchone()
            self._audit(cur, mem0_id, "deleted", {"memory": snapshot}, row, actor)

    def compensate_failed_create(self, mem0_id, actor="system"):
        """Turn a ledger row into an audit tombstone if its Mem0 add is rolled back."""
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_domain WHERE mem0_id=%s FOR UPDATE", (mem0_id,)); before = cur.fetchone()
            if not before: return None
            cur.execute("""UPDATE memory_domain SET status='archived',deleted_at=COALESCE(deleted_at,now()),updated_at=now()
                WHERE mem0_id=%s RETURNING *""", (mem0_id,)); after = cur.fetchone()
            self._audit(cur, mem0_id, "create_rolled_back", before, after, actor); return after

    def recent(self, days=14, limit=20):
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT * FROM memory_domain WHERE deleted_at IS NULL AND status IN ('active','historical')
                AND occurred_at >= now()-(%s*interval '1 day') ORDER BY importance DESC,occurred_at DESC LIMIT %s""", (days, limit)); return cur.fetchall()

    def list(self, filters, limit=100):
        clauses = ["1=1"]; params = []
        if not filters.get("include_deleted"): clauses.append("deleted_at IS NULL")
        for key in ("category", "status"):
            if filters.get(key): clauses.append(f"{key}=%s"); params.append(filters[key])
        if filters.get("from"): clauses.append("occurred_at >= %s"); params.append(filters["from"])
        if filters.get("to"): clauses.append("occurred_at < (%s::date+interval '1 day')"); params.append(filters["to"])
        params.append(limit)
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM memory_domain WHERE {' AND '.join(clauses)} ORDER BY occurred_at DESC LIMIT %s", params); return cur.fetchall()

    def history(self, mem0_id):
        with self.db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM memory_audit_events WHERE mem0_id=%s ORDER BY created_at ASC", (mem0_id,)); return cur.fetchall()

    def create_import_batch(self, label, count, metadata):
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("INSERT INTO memory_import_batches(period_label,item_count,metadata) VALUES (%s,%s,%s) RETURNING *", (label, count, json.dumps(metadata or {}))); return cur.fetchone()

    @staticmethod
    def _jsonable(value):
        if value is None: return None
        if isinstance(value, dict): return {k: DomainRepository._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [DomainRepository._jsonable(v) for v in value]
        if isinstance(value, datetime): return value.isoformat()
        return str(value) if value.__class__.__name__ == "UUID" else value

    def _audit(self, cur, mem0_id, event, before, after, actor):
        cur.execute("INSERT INTO memory_audit_events(mem0_id,event_type,before_state,after_state,actor) VALUES (%s,%s,%s,%s,%s)",
            (mem0_id, event, json.dumps(self._jsonable(before)), json.dumps(self._jsonable(after)), actor))
