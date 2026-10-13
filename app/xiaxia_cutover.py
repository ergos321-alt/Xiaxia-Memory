"""Local operator fence and durable post-cutover journal. Never contacts production.

All admitted writes are serialized. Freeze changes admission first, then waits
for the OS lease, so queued writers cannot start after the freeze. A crashed
writer leaves an unresolved intent; drain must not report success in that case.
"""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class WriteFrozen(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class WriteFence:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "cutover.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS control (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), frozen INTEGER NOT NULL);
                INSERT OR IGNORE INTO control VALUES(1,1);
                CREATE TABLE IF NOT EXISTS baseline (singleton INTEGER PRIMARY KEY, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    operation TEXT NOT NULL, before_state TEXT NOT NULL,
                    after_state TEXT, outcome TEXT, previous_hash TEXT NOT NULL,
                    event_hash TEXT);
            """)

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def try_lease(self):
        # Process-owned OS lease is released on process death. Never expire a
        # live writer by time; a model request may legitimately take minutes.
        with (self.directory / "writer.lock").open("a+b") as handle:
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            acquired = False
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
            try:
                yield acquired
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def is_frozen(self):
        with self.connect() as conn:
            return bool(conn.execute("SELECT frozen FROM control").fetchone()[0])

    def freeze(self, timeout=30):
        with self.connect() as conn:
            conn.execute("UPDATE control SET frozen=1")
        deadline = time.monotonic() + timeout
        while True:
            with self.try_lease() as acquired:
                if acquired:
                    with self.connect() as conn:
                        pending = conn.execute("SELECT count(*) FROM events WHERE after_state IS NULL").fetchone()[0]
                    if pending:
                        raise WriteFrozen("unresolved writer intent; explicit recovery required")
                    return {"frozen": True, "active_writers": 0, "pending_intents": 0}
            if time.monotonic() >= deadline:
                raise WriteFrozen("drain timed out; fence remains frozen")
            time.sleep(0.01)

    def thaw(self):
        with self.try_lease() as acquired:
            if not acquired:
                raise WriteFrozen("writer still active")
            with self.connect() as conn:
                if conn.execute("SELECT count(*) FROM events WHERE after_state IS NULL").fetchone()[0]:
                    raise WriteFrozen("unresolved writer intent")
                conn.execute("UPDATE control SET frozen=0")

    @contextmanager
    def sync_write(self):
        while True:
            if self.is_frozen():
                raise WriteFrozen("memory writes frozen")
            with self.try_lease() as acquired:
                if acquired:
                    if self.is_frozen():
                        raise WriteFrozen("memory writes frozen")
                    yield
                    return
            time.sleep(0.01)

    def initialize(self, snapshot):
        self.freeze()
        with self.try_lease() as acquired:
            if not acquired:
                raise WriteFrozen("writer still active")
            with self.connect() as conn:
                if conn.execute("SELECT count(*) FROM baseline").fetchone()[0]:
                    raise ValueError("journal already initialized; refusing to overwrite")
                conn.execute("INSERT INTO baseline VALUES(1,?)", (canonical(snapshot),))

    def begin(self, operation, before):
        with self.connect() as conn:
            pending = conn.execute("SELECT count(*) FROM events WHERE after_state IS NULL").fetchone()[0]
            if pending:
                raise WriteFrozen("unresolved writer intent")
            last = conn.execute("SELECT after_state,event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            base = conn.execute("SELECT snapshot FROM baseline").fetchone()
            if not base:
                raise WriteFrozen("journal baseline missing")
            expected = json.loads(last[0] if last else base[0])
            if before != expected:
                raise WriteFrozen("unguarded storage mutation detected")
            event_id = str(uuid.uuid4())
            conn.execute("INSERT INTO events(id,operation,before_state,previous_hash) VALUES(?,?,?,?)",
                         (event_id, operation, canonical(before), last[1] if last else digest(expected)))
            return event_id

    def finish(self, event_id, after, outcome):
        with self.connect() as conn:
            row = conn.execute("SELECT operation,before_state,previous_hash,after_state FROM events WHERE id=?",
                               (event_id,)).fetchone()
            if not row or row[3] is not None:
                raise WriteFrozen("invalid journal completion")
            payload = {"id": event_id, "operation": row[0], "before": json.loads(row[1]),
                       "after": after, "outcome": outcome, "previous_hash": row[2]}
            conn.execute("UPDATE events SET after_state=?,outcome=?,event_hash=? WHERE id=?",
                         (canonical(after), outcome, digest(payload), event_id))

    def export(self):
        self.freeze()
        with self.try_lease() as acquired:
            if not acquired:
                raise WriteFrozen("writer still active")
            return self._read_journal()

    def _read_journal(self):
        # Caller holds the writer lease throughout capture/export.
        with self.connect() as conn:
            if not conn.execute("SELECT frozen FROM control").fetchone()[0]:
                raise WriteFrozen("export requires frozen admission")
            if conn.execute("SELECT count(*) FROM events WHERE after_state IS NULL").fetchone()[0]:
                raise WriteFrozen("export has unresolved intents")
            base = conn.execute("SELECT snapshot FROM baseline").fetchone()
            if not base:
                raise ValueError("journal baseline missing")
            events = []
            for row in conn.execute("SELECT id,operation,before_state,after_state,outcome,previous_hash,event_hash FROM events ORDER BY seq"):
                events.append({"id": row[0], "operation": row[1], "before": json.loads(row[2]),
                               "after": json.loads(row[3]), "outcome": row[4], "previous_hash": row[5], "hash": row[6]})
        result = {"schema": "xiaxia-rollback-v1", "baseline": json.loads(base[0]), "events": events}
        validate_journal(result)
        return result


def validate_journal(journal):
    if journal.get("schema") != "xiaxia-rollback-v1":
        raise ValueError("unsupported journal")
    state = journal["baseline"]
    previous = digest(state)
    ids = set()
    for event in journal["events"]:
        payload = {key: value for key, value in event.items() if key != "hash"}
        if (event["id"] in ids or event["before"] != state or
                event["previous_hash"] != previous or digest(payload) != event["hash"]):
            raise ValueError("journal chain damaged")
        for ref, content in event["after"]["sources"].items():
            if ref != "src_" + hashlib.sha256(content.encode()).hexdigest():
                raise ValueError("source evidence damaged")
        if set(state["records"]) - set(event["after"]["records"]):
            raise ValueError("physical memory loss; tombstones required")
        ids.add(event["id"])
        state, previous = event["after"], event["hash"]
    return state


async def capture(adapter):
    records = {}
    links = {}
    for bucket in await adapter._all():
        compat = adapter._compat(bucket)
        if not compat:
            raise WriteFrozen("non-Xiaxia bucket in compatibility-only vault")
        record = adapter._serialize(bucket)
        record.pop("relevance", None)
        records[record["id"]] = record
        links[record["id"]] = {"native_bucket_id": bucket["id"],
                              "source_refs": (bucket.get("metadata") or {}).get("source_refs", [])}
    sources = {path.stem: adapter.source_store.read(path.stem)
               for path in adapter.source_store.root.glob("src_*.source")}
    return {"records": records, "sources": sources, "links": links}


async def recovery_package(adapter, fence, target, pg_bundle, embedding_db_path=""):
    """Freeze, verify live state, and reuse native ZIP + SQLite online snapshot.

    Journal and native archive are both mandatory. This is PG_ONLY recovery,
    never a complete Mem0 history backup. Caller must protect the destination.
    """
    import shutil
    from ombrebrain.storage.backup_archive import build_export_archive_file
    from tools.xiaxia_migration.backup import verify_bundle
    await asyncio.to_thread(fence.freeze)
    with fence.try_lease() as acquired:
        if not acquired:
            raise WriteFrozen("recovery export cannot own writer lease")
        journal = fence._read_journal()
        if await capture(adapter) != validate_journal(journal):
            raise WriteFrozen("vault differs from durable journal; recovery package refused")
        validate_pg_baseline(journal["baseline"], pg_bundle)
        target = Path(target).resolve()
        target.mkdir(exist_ok=False)
        path = target / "rollback-journal.json"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(canonical(journal)); handle.flush(); os.fsync(handle.fileno())
        with fence.connect() as source, sqlite3.connect(target / "cutover.sqlite3") as destination:
            source.backup(destination)
        vault = adapter.source_store.root.parent
        temp, _manifest = build_export_archive_file(str(vault), embedding_db_path,
                                                   {"version": "3.6.14", "embedding": {}})
        shutil.move(temp, target / "ombre.zip")
        manifest = {"schema": "xiaxia-cutover-recovery-v1", "sqlite_history": "NOT_BACKED_UP",
                    "complete_backup": False, "pg_baseline": str(Path(pg_bundle).resolve()),
                    "pg_dump_sha256": hashlib.sha256((Path(pg_bundle)/"mem0_tables.dump").read_bytes()).hexdigest(),
                    "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}}
        (target / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
        return manifest


def validate_pg_baseline(snapshot, pg_bundle):
    """The journal must begin at this PG snapshot, not a later edited vault."""
    from tools.xiaxia_migration.importer import _load_snapshot
    records, _stats = _load_snapshot(pg_bundle, mode="PG_ONLY")
    expected = {row["id"]: row for row in records if not row["source_only_tombstone"]}
    if set(snapshot["records"]) != set(expected):
        raise WriteFrozen("journal baseline IDs differ from final PG snapshot")
    fields = ("memory_text", "category", "subtype", "importance", "occurred_at", "source", "status",
              "supersedes", "superseded_by", "metadata", "created_at", "updated_at", "deleted_at")
    for mid, record in snapshot["records"].items():
        if any(record.get(key) != expected[mid].get(key) for key in fields):
            raise WriteFrozen("journal baseline fields differ from final PG snapshot")
    tombstones = [row for row in records if row["source_only_tombstone"]]
    evidence = []
    for text in snapshot["sources"].values():
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict) and document.get("kind") == "xiaxia_mem0_source_only_tombstone":
            evidence.append(document.get("record"))
    if any(row not in evidence for row in tombstones):
        raise WriteFrozen("source-only PG tombstone absent from journal baseline")


class JournaledAdapter:
    """Only public mutators admit writes; native tools are not exposed by this service."""
    def __init__(self, adapter, fence):
        self.adapter, self.fence = adapter, fence

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.adapter, name)

    async def _write(self, name, **kwargs):
        while True:
            if self.fence.is_frozen():
                raise WriteFrozen("memory writes frozen")
            with self.fence.try_lease() as acquired:
                if acquired:
                    if self.fence.is_frozen():
                        raise WriteFrozen("memory writes frozen")
                    before = await capture(self.adapter)
                    event = self.fence.begin(name, before)
                    try:
                        result = await getattr(self.adapter, name)(**kwargs)
                    except BaseException:
                        # Even an unsuccessful batch may have durable partial
                        # writes. Record those states, never lose them on replay.
                        self.fence.finish(event, await capture(self.adapter), "FAILED_WITH_CAPTURED_STATE")
                        raise
                    self.fence.finish(event, await capture(self.adapter), "COMMITTED")
                    return result
            await asyncio.sleep(0.01)

    async def save(self, **kwargs):
        return await self._write("save", **kwargs)

    async def update(self, mem0_id, **kwargs):
        return await self._write("update", mem0_id=mem0_id, **kwargs)

    async def delete(self, mem0_id, actor="api"):
        return await self._write("delete", mem0_id=mem0_id, actor=actor)

    async def recover(self):
        # Freeze first. The OS lease proves the original process no longer owns
        # the operation; pending work is never recovered while a writer is live.
        with self.fence.connect() as conn:
            conn.execute("UPDATE control SET frozen=1")
        with self.fence.try_lease() as acquired:
            if not acquired:
                raise WriteFrozen("cannot recover a live writer")
            with self.fence.connect() as conn:
                rows = conn.execute("SELECT id FROM events WHERE after_state IS NULL").fetchall()
            for (event,) in rows:
                self.fence.finish(event, await capture(self.adapter), "RECOVERED_INTERRUPTED_STATE")
        return self.fence.freeze()


def install_legacy_fence(app, fence):
    """Stage on the existing Flask app, without altering its source or auth.

    Covers the whole HTTP request (including multi-item saves) and direct calls
    to the actual engine from jobs. This must be installed before serving.
    """
    import threading
    from flask import g, jsonify, request
    local = threading.local()
    original = app.extensions["memory_engine"]

    @contextmanager
    def admitted():
        if getattr(local, "admitted", False):
            yield
            return
        with fence.sync_write():
            local.admitted = True
            try:
                yield
            finally:
                local.admitted = False

    class EngineProxy:
        def __getattr__(self, name):
            target = getattr(original, name)
            if name not in {"add_inferred", "add_structured", "update", "delete", "archive_period"}:
                return target
            def guarded(*args, **kwargs):
                with admitted():
                    return target(*args, **kwargs)
            return guarded

    app.extensions["memory_engine"] = EngineProxy()

    @app.before_request
    def before():
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.path not in {
            "/api/v1/memories/search", "/admin/login", "/admin/cutover/freeze", "/admin/cutover/thaw"}:
            lease = admitted()
            try:
                lease.__enter__()
            except WriteFrozen:
                return jsonify({"error": "memory writes frozen"}), 503
            g.xiaxia_write_lease = lease

    @app.teardown_request
    def after(_error):
        lease = g.pop("xiaxia_write_lease", None)
        if lease:
            lease.__exit__(None, None, None)

    # Free Render has no shell. Stage a bounded, separately authenticated
    # control path using the existing administrator secret, not the Actions
    # token. No memory data, environment values or journal are exposed here.
    def operator_authorized():
        import hmac
        expected = app.config.get("ADMIN_PASSWORD", "")
        return bool(expected) and hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), ("Bearer " + expected).encode())

    @app.post("/admin/cutover/freeze")
    def cutover_freeze():
        if not operator_authorized():
            return jsonify({"error": "Unauthorized"}), 401
        try:
            return jsonify(fence.freeze(timeout=30))
        except WriteFrozen:
            return jsonify({"frozen": True, "drained": False}), 503

    @app.post("/admin/cutover/thaw")
    def cutover_thaw():
        if not operator_authorized():
            return jsonify({"error": "Unauthorized"}), 401
        if app.config.get("XIAXIA_LEGACY_ALLOW_THAW") is False:
            return jsonify({"error": "legacy write release is not approved"}), 503
        try:
            fence.thaw()
            return jsonify({"frozen": False})
        except WriteFrozen:
            return jsonify({"error": "unresolved writer"}), 503
