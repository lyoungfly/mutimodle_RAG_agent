import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str
    csrf_token: str = ""

    def public(self):
        return {"id": self.id, "username": self.username, "role": self.role}


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()


class AccessStore:
    def __init__(self, root: Path):
        self.path = root / "access.sqlite3"
        self.lock = RLock()
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_grants (
                    collection TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY(collection,user_id)
                );
                CREATE TABLE IF NOT EXISTS document_policies (
                    document_id TEXT PRIMARY KEY, restricted INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document_grants (
                    document_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY(document_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
            """)

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

    def enabled(self):
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def create_user(self, username: str, password: str, bootstrap=False):
        salt = secrets.token_hex(16)
        encoded = password_hash(password, salt)
        identity = secrets.token_hex(16)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if bootstrap and db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ValueError("管理员已创建，请登录。")
            try:
                db.execute("INSERT INTO users(id,username,salt,password,role) VALUES(?,?,?,?,?)",
                           (identity, username, salt, encoded, "admin" if bootstrap else "member"))
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在。") from exc
        return {"id": identity, "username": username, "role": "admin" if bootstrap else "member"}

    def login(self, username: str, password: str):
        with self.db() as db:
            user = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        computed = password_hash(password, user["salt"] if user else "0" * 32)
        if not user or not hmac.compare_digest(computed, user["password"]):
            return None
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            # 每名成员最多保留十个会话。
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash NOT IN (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT 9)", (user["id"], user["id"]))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, time.time() + 12 * 3600))
        return token, Principal(user["id"], user["username"], user["role"], csrf)

    def session(self, token):
        if not token or len(token) > 256:
            return None
        with self.db() as db:
            row = db.execute("SELECT u.id,u.username,u.role,s.csrf FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>? AND u.active=1", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return Principal(row["id"], row["username"], row["role"], row["csrf"]) if row else None

    def logout(self, token):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def allowed(self, actor: Principal, collection: str, write=False, document_id=None):
        with self.db() as db:
            enabled = bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())
            if not enabled:
                return actor.id == "local"
            user = db.execute("SELECT role FROM users WHERE id=? AND active=1", (actor.id,)).fetchone()
            if not user:
                return False
            if user["role"] == "admin":
                return True
            grant = db.execute("SELECT role FROM collection_grants WHERE collection=? AND user_id=?", (collection, actor.id)).fetchone()
            if not grant or (write and grant[0] != "editor"):
                return False
            if document_id:
                policy = db.execute("SELECT restricted FROM document_policies WHERE document_id=?", (document_id,)).fetchone()
                if policy and policy[0]:
                    grant = db.execute("SELECT role FROM document_grants WHERE document_id=? AND user_id=?", (document_id, actor.id)).fetchone()
                    return bool(grant and (not write or grant[0] == "editor"))
            return True

    def grant(self, collection, user_id, role, document_id=None, restricted=True):
        with self.db() as db:
            if user_id and not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise ValueError("成员不存在。")
            if document_id:
                db.execute("INSERT INTO document_policies VALUES(?,?) ON CONFLICT(document_id) DO UPDATE SET restricted=excluded.restricted", (document_id, int(restricted)))
                if user_id:
                    db.execute("DELETE FROM document_grants WHERE document_id=? AND user_id=?", (document_id, user_id))
                    if role != "none":
                        db.execute("INSERT INTO document_grants VALUES(?,?,?)", (document_id, user_id, role))
            else:
                db.execute("DELETE FROM collection_grants WHERE collection=? AND user_id=?", (collection, user_id))
                if role != "none":
                    db.execute("INSERT INTO collection_grants VALUES(?,?,?)", (collection, user_id, role))

    def audit(self, actor, action, target="", detail=None):
        with self.db() as db:
            db.execute("INSERT INTO audit(at,actor,action,target,detail) VALUES(?,?,?,?,?)", (time.time(), actor, action, target[:256], json.dumps(detail or {}, ensure_ascii=False)))
            db.execute("DELETE FROM audit WHERE id <= (SELECT COALESCE(MAX(id),0)-10000 FROM audit)")
