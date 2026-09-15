import json
import os
import logging
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Event, RLock

from fastapi import HTTPException


class JobCancelled(Exception):
    pass


logger = logging.getLogger(__name__)


class JobManager:
    """单进程有界任务队列；持久化结果，不在重启后隐式重放模型请求。"""
    def __init__(self, root: Path):
        self.root, self.path = root, root / "jobs.sqlite3"
        self.lock = RLock()
        self.slots = BoundedSemaphore(24)
        self.executor = None
        self.cancellations = {}
        self.process_lock = None
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, collection TEXT NOT NULL,
                kind TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, events TEXT NOT NULL, result TEXT,
                error TEXT NOT NULL DEFAULT '', document_ids TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )""")

    @contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def start(self):
        with self.lock:
            if self.executor:
                return
            lockfile = open(self.root / "jobs.lock", "a+b")
            try:
                lockfile.seek(0, os.SEEK_END)
                if lockfile.tell() == 0:
                    lockfile.write(b"0")
                    lockfile.flush()
                lockfile.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                lockfile.close()
                raise RuntimeError("同一数据目录已有后台任务服务运行，请使用单个服务进程。") from exc
            self.process_lock = lockfile
            with self.db() as db:
                db.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE status IN ('queued','running')", ("服务已重启，原任务中断；请重新提交。", time.time()))
            self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="enterprise-job")

    def stop(self):
        with self.lock:
            for flag in self.cancellations.values():
                flag.set()
            executor = self.executor
            self.executor = None
        if executor:
            executor.shutdown(wait=True)
        if self.process_lock:
            self.process_lock.close()
            self.process_lock = None

    def _event(self, identity, event):
        if isinstance(event, str):
            event = {"message": event}
        safe = {key: str(event[key])[:1000] for key in ("stage", "status", "tool", "message") if key in event}
        safe["at"] = time.time()
        with self.db() as db:
            row = db.execute("SELECT events FROM jobs WHERE id=?", (identity,)).fetchone()
            if row:
                events = json.loads(row[0])[-199:] + [safe]
                db.execute("UPDATE jobs SET events=?,updated_at=? WHERE id=?", (json.dumps(events, ensure_ascii=False), time.time(), identity))

    def submit(self, owner, collection, kind, work, document_ids=()):
        if not self.executor:
            raise RuntimeError("后台任务服务未启动，请重启 PaperMind。")
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429, "任务队列已满，请等待现有任务完成。")
        identity, now, flag = uuid.uuid4().hex, time.time(), Event()
        try:
            with self.db() as db:
                if db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 6:
                    raise HTTPException(429, "每名成员最多同时提交六个任务。")
                db.execute("DELETE FROM jobs WHERE status NOT IN ('queued','running') AND (updated_at<? OR id IN (SELECT id FROM jobs WHERE status NOT IN ('queued','running') ORDER BY created_at DESC LIMIT -1 OFFSET 199))", (now - 30 * 86400,))
                db.execute("INSERT INTO jobs(id,owner,collection,kind,status,created_at,updated_at,events,document_ids) VALUES(?,?,?,?,?,?,?,?,?)", (identity, owner, collection, kind, "queued", now, now, "[]", json.dumps(list(document_ids))))
                self.cancellations[identity] = flag
            self.executor.submit(self._run, identity, flag, work)
        except Exception:
            with self.lock:
                self.cancellations.pop(identity, None)
            with self.db() as db:
                db.execute("DELETE FROM jobs WHERE id=? AND status='queued'", (identity,))
            self.slots.release()
            raise
        return self.get(identity)

    def _run(self, identity, flag, work):
        def check():
            if flag.is_set():
                raise JobCancelled()

        try:
            check()
            with self.db() as db:
                db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (time.time(), identity))
            self._event(identity, {"stage": "started", "message": "任务开始执行。"})
            result = work(lambda event: self._event(identity, event), flag.is_set)
            check()
            result = {**result, "completed_at": result.get("completed_at") or datetime.now(timezone.utc).isoformat()}
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 4 * 1024**2:
                raise ValueError("任务结果超过 4 MB，请缩小资料或分析范围。")
            with self.db() as db:
                previous = json.loads(db.execute("SELECT document_ids FROM jobs WHERE id=?", (identity,)).fetchone()[0])
                sources = sorted(set(previous + result.get("document_ids", [])))
                db.execute("UPDATE jobs SET status='succeeded',result=?,document_ids=?,updated_at=? WHERE id=?", (encoded, json.dumps(sources), time.time(), identity))
            self._event(identity, {"stage": "complete", "message": "任务完成，可查看结果与来源。"})
        except Exception as exc:
            logger.warning("Enterprise job %s failed (%s)", identity, type(exc).__name__)
            cancelled = flag.is_set() or isinstance(exc, JobCancelled)
            # 供应商异常可能包含密钥或文档，不保存原始异常正文。
            error = "任务已取消。" if cancelled else "任务执行失败。请检查模型配置、依赖安装及输入范围后重试。"
            if isinstance(exc, HTTPException):
                error = "任务所需的资料访问权限已变更或不可用。"
            elif type(exc).__module__.startswith("papermind.enterprise") and len(str(exc)) < 500:
                error = str(exc)
            elif type(exc) in {ValueError, RuntimeError, ImportError}:
                safe_markers = ("依赖", "安装", "未配置", "未启用", "超过", "不支持", "列", "数值", "分组", "表格", "筛选", "公式")
                if any(marker in str(exc) for marker in safe_markers) and len(str(exc)) < 500:
                    error = str(exc)
            with self.db() as db:
                db.execute("UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=?", ("cancelled" if cancelled else "failed", error, time.time(), identity))
        finally:
            with self.lock:
                self.cancellations.pop(identity, None)
            self.slots.release()

    def get(self, identity):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        data = dict(row)
        for field in ("events", "result", "document_ids"):
            data[field] = json.loads(data[field]) if data[field] else None
        return data

    def list(self, owner, collection, admin=False):
        with self.db() as db:
            rows = db.execute("SELECT id,owner,collection,kind,status,created_at,updated_at,error,document_ids FROM jobs WHERE collection=? AND (? OR owner=?) ORDER BY created_at DESC LIMIT 100", (collection, int(admin), owner)).fetchall()
        return [{**dict(row), "document_ids": json.loads(row["document_ids"])} for row in rows]

    def cancel(self, identity):
        with self.db() as db:
            flag = self.cancellations.get(identity)
            if flag:
                flag.set()
                db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (identity,))
        return self.get(identity)
