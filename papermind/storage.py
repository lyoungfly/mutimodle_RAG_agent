import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import RLock

import numpy as np

from papermind.models import Chunk, Document, Figure, Paragraph, Section, Table


def document_from_dict(data: dict) -> Document:
    return Document(
        data["document_id"],
        data["title"],
        [
            Section(s["title"], s["level"], [Paragraph(**p) for p in s["paragraphs"]])
            for s in data.get("sections", [])
        ],
        data.get("metadata", {}),
        [Table(**t) for t in data.get("tables", [])],
        [Figure(**f) for f in data.get("figures", [])],
    )


class DocumentStore:
    def __init__(self, root: Path, max_chunks: int = 50000):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "uploads").mkdir(exist_ok=True)
        self.max_chunks = max_chunks
        self._lock = RLock()
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, collection TEXT NOT NULL, filename TEXT NOT NULL,
                    suffix TEXT NOT NULL, body TEXT NOT NULL, indexed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    body TEXT NOT NULL, vector BLOB, fingerprint TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS document_collection ON documents(collection);
                CREATE INDEX IF NOT EXISTS chunk_document ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS revisions (collection TEXT PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS visual_assets (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL, png BLOB NOT NULL,
                    PRIMARY KEY(document_id,asset_id)
                );
                CREATE TABLE IF NOT EXISTS image_vectors (
                    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    vector BLOB NOT NULL, fingerprint TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        with self._lock:
            db = sqlite3.connect(self.root / "papermind.sqlite3", timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                with db:
                    yield db
            finally:
                db.close()

    def register(self, document: Document, collection: str, filename: str, suffix: str):
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO documents(id,collection,filename,suffix,body) VALUES(?,?,?,?,?)",
                (
                    document.document_id,
                    collection,
                    filename,
                    suffix,
                    json.dumps(asdict(document), ensure_ascii=False),
                ),
            )

    def get(self, document_id: str, collection: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM documents WHERE id=? AND collection=?",
                (document_id, collection),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            return {**dict(row), "body": json.loads(row["body"])}

    def list_collections(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT collection AS collection_id, COUNT(*) AS document_count "
                "FROM documents GROUP BY collection ORDER BY collection"
            ).fetchall()
            return [dict(row) for row in rows]

    def list_documents(self, collection: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT d.id AS document_id,d.filename,d.indexed,
                COUNT(c.id) AS chunk_count FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
                WHERE d.collection=? GROUP BY d.id ORDER BY d.filename,d.id""",
                (collection,),
            ).fetchall()
            return [dict(row) for row in rows]

    def replace_index(
        self,
        document: Document,
        collection: str,
        chunks: list[Chunk],
        vectors: np.ndarray | None,
        fingerprint: str,
        assets: dict[str, bytes] | None = None,
        image_vectors: dict[str, np.ndarray] | None = None,
        image_fingerprint: str = "",
    ):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM documents WHERE id=? AND collection=?",
                (document.document_id, collection),
            ).fetchone():
                raise KeyError(document.document_id)
            total = db.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id!=?",
                (document.document_id,),
            ).fetchone()[0]
            if total + len(chunks) > self.max_chunks:
                raise ValueError(f"Index exceeds the {self.max_chunks} chunk limit")
            db.execute(
                "DELETE FROM chunks WHERE document_id=?", (document.document_id,)
            )
            db.executemany(
                "INSERT INTO chunks VALUES(?,?,?,?,?)",
                [
                    (
                        c.chunk_id,
                        c.document_id,
                        json.dumps(asdict(c), ensure_ascii=False),
                        None
                        if vectors is None
                        else np.asarray(vectors[i], dtype="<f4").tobytes(),
                        fingerprint,
                    )
                    for i, c in enumerate(chunks)
                ],
            )
            db.execute(
                "DELETE FROM visual_assets WHERE document_id=?", (document.document_id,)
            )
            db.executemany(
                "INSERT INTO visual_assets VALUES(?,?,?)",
                [
                    (document.document_id, key, data)
                    for key, data in (assets or {}).items()
                ],
            )
            db.executemany(
                "INSERT INTO image_vectors VALUES(?,?,?)",
                [
                    (key, np.asarray(vector, dtype="<f4").tobytes(), image_fingerprint)
                    for key, vector in (image_vectors or {}).items()
                ],
            )
            db.execute(
                "UPDATE documents SET body=?,indexed=1 WHERE id=?",
                (
                    json.dumps(asdict(document), ensure_ascii=False),
                    document.document_id,
                ),
            )
            db.execute(
                """INSERT INTO revisions VALUES(?,1) ON CONFLICT(collection)
                       DO UPDATE SET version=version+1""",
                (collection,),
            )

    def revision(self, collection: str) -> int:
        with self.connection() as db:
            row = db.execute(
                "SELECT version FROM revisions WHERE collection=?", (collection,)
            ).fetchone()
            return row[0] if row else 0

    def snapshot(
        self, collection: str
    ) -> tuple[int, list[Chunk], list[bytes | None], set[str]]:
        return self.snapshot_with_images(collection)[:4]

    def snapshot_with_images(self, collection: str):
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT version FROM revisions WHERE collection=?", (collection,)
            ).fetchone()
            revision = row[0] if row else 0
            rows = db.execute(
                """SELECT c.* FROM chunks c JOIN documents d ON c.document_id=d.id
                                WHERE d.collection=? ORDER BY c.id""",
                (collection,),
            ).fetchall()
            images = db.execute(
                """SELECT v.* FROM image_vectors v
                JOIN chunks c ON c.id=v.chunk_id JOIN documents d ON c.document_id=d.id
                WHERE d.collection=? ORDER BY v.chunk_id""",
                (collection,),
            ).fetchall()
            return (
                revision,
                [Chunk(**json.loads(r["body"])) for r in rows],
                [r["vector"] for r in rows],
                {r["fingerprint"] for r in rows},
                [dict(row) for row in images],
            )

    def asset(self, document_id: str, asset_id: str, collection: str) -> bytes:
        with self.connection() as db:
            row = db.execute(
                """SELECT a.png FROM visual_assets a
                JOIN documents d ON a.document_id=d.id
                WHERE d.id=? AND a.asset_id=? AND d.collection=?""",
                (document_id, asset_id, collection),
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            return row[0]

    def source(self, chunk_id: str, collection: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                """SELECT c.body,d.filename,d.suffix FROM chunks c
                JOIN documents d ON c.document_id=d.id WHERE c.id=? AND d.collection=?""",
                (chunk_id, collection),
            ).fetchone()
            if row is None:
                raise KeyError(chunk_id)
            chunk = json.loads(row["body"])
            return {**chunk, "filename": row["filename"], "suffix": row["suffix"]}

    def raw_path(self, record: dict) -> Path:
        # 路径仅由内部摘要和已验证的扩展名构造，不接受用户提供的路径。
        path = self.root / "uploads" / (record["id"] + record["suffix"])
        if not path.resolve().is_relative_to(self.root / "uploads"):
            raise ValueError("Invalid source path")
        return path
