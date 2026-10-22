"""Consistent SQLite snapshots, published only after an integrity check."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

_backup_lock = threading.Lock()


def create_backup(database: Path, directory: Path) -> dict:
    with _backup_lock:
        if not database.is_file():
            raise RuntimeError("业务数据库不存在，不能生成空备份")
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        filename = f"factorypulse-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.sqlite3"
        target = directory / filename
        temporary = directory / (filename + ".partial")
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)) as source:
                with closing(sqlite3.connect(temporary)) as destination:
                    source.backup(destination, pages=256, sleep=.05)
                    result = destination.execute("PRAGMA integrity_check").fetchall()
                    if result != [("ok",)]:
                        raise RuntimeError("备份完整性检查未通过")
                    tables = {row[0] for row in destination.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not {"records", "settings", "work_orders", "audit_events"}.issubset(tables):
                        raise RuntimeError("备份缺少必要业务表")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            return {"filename": filename, "created_at": now.isoformat(), "size_bytes": target.stat().st_size, "integrity": "ok"}
        finally:
            temporary.unlink(missing_ok=True)


def install_backups(app, database, connect):
    from fastapi import HTTPException
    from .security import principal

    directory = Path(os.getenv("FACTORYPULSE_BACKUP_DIR", database.parent / "backups"))
    stop = threading.Event()
    state_lock = threading.Lock()
    state = {"status": "not_started", "last_success": None, "last_error": ""}
    with connect() as connection:
        previous = connection.execute("SELECT content FROM audit_events WHERE event_type='database_backup' ORDER BY event_id DESC LIMIT 1").fetchone()
    if previous:
        try:
            snapshot = json.loads(previous[0])
            filename = snapshot.get("filename", "")
            if filename and Path(filename).name == filename:
                state.update(status="ready", last_success=snapshot)
        except (ValueError, TypeError, AttributeError):
            pass
    worker = None

    def admin():
        user = principal()
        if user and user["role"] != "developer":
            raise HTTPException(403, "备份管理需要管理员权限")

    def perform():
        with state_lock:
            if state["status"] == "running":
                raise HTTPException(409, "备份正在生成，请稍后刷新")
            state["status"] = "running"
        try:
            snapshot = create_backup(database, directory)
            with connect() as connection:
                connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)", ("database_backup", snapshot["filename"], json.dumps(snapshot), snapshot["created_at"]))
            with state_lock:
                state.update(status="ready", last_success=snapshot, last_error="")
            return snapshot
        except Exception:
            with state_lock:
                state.update(status="failed", last_error="备份未成功，请检查备份目录权限与可用空间")
            raise

    def loop():
        while not stop.is_set():
            try:
                perform()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Database backup failed")
            if stop.wait(24 * 3600):
                break

    def start():
        nonlocal worker
        if os.getenv("FACTORYPULSE_AUTO_BACKUP", "1") == "0":
            with state_lock:
                state["status"] = "disabled"
            return
        stop.clear()
        worker = threading.Thread(target=loop, name="factorypulse-backup", daemon=True)
        worker.start()

    def shutdown():
        stop.set()
        if worker:
            worker.join(timeout=5)

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application) as inherited_state:
            start()
            try:
                yield inherited_state
            finally:
                shutdown()

    app.router.lifespan_context = lifespan

    @app.get("/api/backups/status")
    def status():
        admin()
        with state_lock:
            result=dict(state)
        snapshot=result.get("last_success")
        if snapshot and result["status"]!="running":
            filename=snapshot.get("filename","")
            try:
                path=directory/filename
                available=bool(filename and Path(filename).name==filename and path.is_file() and path.stat().st_size==snapshot.get("size_bytes"))
            except OSError:
                available=False
            result["backup_available"]=available
            if not available:
                result.update(status="failed",last_error="最近备份文件缺失、大小变化或无法访问，请检查备份目录并重新备份")
        else:result["backup_available"]=None
        return result

    @app.post("/api/backups/create")
    def manual():
        admin()
        try:
            return {"success": True, "backup": perform()}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "备份未成功，请检查备份目录权限与可用空间")
