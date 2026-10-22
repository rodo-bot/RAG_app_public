from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import DATABASE_PATH, ensure_data_dirs
from .text import DetectedEntity


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    indexed_at TEXT,
    error TEXT,
    relative_path TEXT NOT NULL DEFAULT '',
    family_key TEXT NOT NULL DEFAULT '',
    revision_label TEXT NOT NULL DEFAULT '',
    revision_rank INTEGER NOT NULL DEFAULT 0,
    version_detected INTEGER NOT NULL DEFAULT 0,
    is_current INTEGER NOT NULL DEFAULT 1,
    file_type TEXT NOT NULL DEFAULT 'pdf'
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_type TEXT NOT NULL,
    text_source TEXT NOT NULL,
    embedded_text TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    char_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    width_points REAL NOT NULL,
    height_points REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    red_markup_score REAL NOT NULL DEFAULT 0,
    preview_path TEXT NOT NULL,
    thumbnail_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source_label TEXT NOT NULL DEFAULT '',
    UNIQUE(document_id, page_number)
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    page_id UNINDEXED,
    document_name,
    page_type,
    content,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    display_value TEXT NOT NULL,
    UNIQUE(entity_type, normalized_value)
);

CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    context TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.8,
    UNIQUE(entity_id, page_id, context)
);

CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_mentions_page ON mentions(page_id);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_entities_normalized ON entities(normalized_value);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeDB:
    def __init__(self, path: Path = DATABASE_PATH):
        ensure_data_dirs()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
            migrations = {
                "relative_path": "TEXT NOT NULL DEFAULT ''",
                "family_key": "TEXT NOT NULL DEFAULT ''",
                "revision_label": "TEXT NOT NULL DEFAULT ''",
                "revision_rank": "INTEGER NOT NULL DEFAULT 0",
                "version_detected": "INTEGER NOT NULL DEFAULT 0",
                "is_current": "INTEGER NOT NULL DEFAULT 1",
                "file_type": "TEXT NOT NULL DEFAULT 'pdf'",
            }
            for name, definition in migrations.items():
                if name not in existing_columns:
                    connection.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
            page_columns = {row["name"] for row in connection.execute("PRAGMA table_info(pages)")}
            if "source_label" not in page_columns:
                connection.execute("ALTER TABLE pages ADD COLUMN source_label TEXT NOT NULL DEFAULT ''")

    def get_document_by_path(self, path: Path) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM documents WHERE path=?", (str(path.resolve()),)).fetchone()

    def upsert_document(
        self,
        path: Path,
        sha256: str,
        size_bytes: int,
        mtime_ns: int,
        relative_path: str = "",
        family_key: str = "",
        revision_label: str = "",
        revision_rank: int = 0,
        version_detected: bool = False,
        file_type: str = "pdf",
    ) -> int:
        resolved = str(path.resolve())
        relative_path = relative_path or path.name
        family_key = family_key or path.stem.lower()
        with self.connect() as connection:
            existing = connection.execute("SELECT id FROM documents WHERE path=?", (resolved,)).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE documents
                    SET name=?,sha256=?,size_bytes=?,mtime_ns=?,status='indexing',error=NULL,
                        relative_path=?,family_key=?,revision_label=?,revision_rank=?,version_detected=?,file_type=?
                    WHERE id=?
                    """,
                    (
                        path.name, sha256, size_bytes, mtime_ns, relative_path, family_key,
                        revision_label, revision_rank, int(version_detected), file_type, existing["id"],
                    ),
                )
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    path,name,sha256,size_bytes,mtime_ns,status,relative_path,family_key,
                    revision_label,revision_rank,version_detected,is_current,file_type
                ) VALUES(?,?,?,?,?,'indexing',?,?,?,?,?,1,?)
                """,
                (
                    resolved, path.name, sha256, size_bytes, mtime_ns, relative_path,
                    family_key, revision_label, revision_rank, int(version_detected), file_type,
                ),
            )
            return int(cursor.lastrowid)

    def update_document_version(
        self,
        path: Path,
        relative_path: str,
        family_key: str,
        revision_label: str,
        revision_rank: int,
        version_detected: bool,
        file_type: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET relative_path=?,family_key=?,revision_label=?,revision_rank=?,version_detected=?,
                    file_type=COALESCE(?,file_type)
                WHERE path=?
                """,
                (
                    relative_path, family_key, revision_label, revision_rank,
                    int(version_detected), file_type, str(path.resolve()),
                ),
            )

    def find_relocatable_document(self, sha256: str, name: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE sha256=? AND name=? AND status='ready'",
                (sha256, name),
            ).fetchall()
        return next((row for row in rows if not Path(row["path"]).exists()), None)

    def relocate_document(
        self,
        document_id: int,
        path: Path,
        size_bytes: int,
        mtime_ns: int,
        relative_path: str,
        family_key: str,
        revision_label: str,
        revision_rank: int,
        version_detected: bool,
        file_type: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET path=?,name=?,size_bytes=?,mtime_ns=?,relative_path=?,family_key=?,
                    revision_label=?,revision_rank=?,version_detected=?,file_type=COALESCE(?,file_type),error=NULL
                WHERE id=?
                """,
                (
                    str(path.resolve()), path.name, size_bytes, mtime_ns, relative_path,
                    family_key, revision_label, revision_rank, int(version_detected), file_type, document_id,
                ),
            )
            connection.execute(
                "UPDATE pages_fts SET document_name=? WHERE page_id IN (SELECT id FROM pages WHERE document_id=?)",
                (path.name, document_id),
            )

    def list_document_records(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM documents ORDER BY id").fetchall()

    def remove_document(self, document_id: int) -> list[str]:
        with self.connect() as connection:
            asset_rows = connection.execute(
                "SELECT preview_path,thumbnail_path FROM pages WHERE document_id=?",
                (document_id,),
            ).fetchall()
            page_ids = [row[0] for row in connection.execute("SELECT id FROM pages WHERE document_id=?", (document_id,))]
            if page_ids:
                placeholders = ",".join("?" for _ in page_ids)
                connection.execute(f"DELETE FROM pages_fts WHERE page_id IN ({placeholders})", page_ids)
            connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
            connection.execute("DELETE FROM entities WHERE NOT EXISTS (SELECT 1 FROM mentions WHERE mentions.entity_id=entities.id)")
            return [value for row in asset_rows for value in (row["preview_path"], row["thumbnail_path"]) if value]

    def recompute_current_versions(self) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE documents SET is_current=1 WHERE version_detected=0")
            connection.execute("UPDATE documents SET is_current=0 WHERE version_detected=1")
            connection.execute(
                """
                UPDATE documents
                SET is_current=1
                WHERE version_detected=1
                  AND revision_rank=(
                      SELECT max(newest.revision_rank)
                      FROM documents newest
                      WHERE newest.family_key=documents.family_key AND newest.version_detected=1
                  )
                """
            )

    def clear_document_pages(self, document_id: int) -> None:
        with self.connect() as connection:
            page_ids = [row[0] for row in connection.execute("SELECT id FROM pages WHERE document_id=?", (document_id,))]
            if page_ids:
                placeholders = ",".join("?" for _ in page_ids)
                connection.execute(f"DELETE FROM pages_fts WHERE page_id IN ({placeholders})", page_ids)
            connection.execute("DELETE FROM pages WHERE document_id=?", (document_id,))
            connection.execute("DELETE FROM entities WHERE NOT EXISTS (SELECT 1 FROM mentions WHERE mentions.entity_id=entities.id)")

    def get_document_asset_paths(self, document_id: int) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT preview_path,thumbnail_path FROM pages WHERE document_id=?",
                (document_id,),
            ).fetchall()
            return [value for row in rows for value in (row["preview_path"], row["thumbnail_path"]) if value]

    def add_page(
        self, document_id: int, document_name: str, record: dict[str, Any],
        entities: list[DetectedEntity], connection: sqlite3.Connection | None = None,
    ) -> int:
        # The indexer shares one transaction across a small batch of pages.
        # Direct callers retain the original one-page transaction behavior.
        with (nullcontext(connection) if connection is not None else self.connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO pages(
                    document_id,page_number,page_type,text_source,embedded_text,ocr_text,search_text,
                    char_count,word_count,image_count,width_points,height_points,confidence,
                    red_markup_score,preview_path,thumbnail_path,metadata_json
                    ,source_label
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document_id,
                    record["page_number"],
                    record["page_type"],
                    record["text_source"],
                    record["embedded_text"],
                    record["ocr_text"],
                    record["search_text"],
                    record["char_count"],
                    record["word_count"],
                    record["image_count"],
                    record["width_points"],
                    record["height_points"],
                    record["confidence"],
                    record["red_markup_score"],
                    record["preview_path"],
                    record["thumbnail_path"],
                    json.dumps(record.get("metadata", {}), ensure_ascii=False),
                    record.get("source_label", ""),
                ),
            )
            page_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO pages_fts(page_id,document_name,page_type,content) VALUES(?,?,?,?)",
                (page_id, document_name, record["page_type"], record["search_text"]),
            )
            for entity in entities:
                connection.execute(
                    "INSERT OR IGNORE INTO entities(entity_type,normalized_value,display_value) VALUES(?,?,?)",
                    (entity.entity_type, entity.normalized_value, entity.display_value),
                )
                entity_row = connection.execute(
                    "SELECT id FROM entities WHERE entity_type=? AND normalized_value=?",
                    (entity.entity_type, entity.normalized_value),
                ).fetchone()
                context_start = max(0, entity.start - 100)
                context_end = min(len(record["search_text"]), entity.end + 140)
                context = record["search_text"][context_start:context_end].strip()
                connection.execute(
                    "INSERT OR IGNORE INTO mentions(entity_id,page_id,context) VALUES(?,?,?)",
                    (entity_row["id"], page_id, context),
                )
            return page_id

    def finish_document(self, document_id: int, page_count: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE documents SET page_count=?, status='ready', indexed_at=?, error=NULL WHERE id=?",
                (page_count, utc_now(), document_id),
            )

    def fail_document(self, document_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE documents SET status='error', error=? WHERE id=?", (error[:2000], document_id))

    def stats(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready'").fetchone()[0]),
                "current_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND is_current=1").fetchone()[0]),
                "superseded_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND is_current=0").fetchone()[0]),
                "pages": int(connection.execute("SELECT count(*) FROM pages").fetchone()[0]),
                "image_only_pages": int(connection.execute("SELECT count(*) FROM pages WHERE text_source='none'").fetchone()[0]),
                "entities": int(connection.execute("SELECT count(*) FROM entities").fetchone()[0]),
                "pdf_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND file_type='pdf'").fetchone()[0]),
                "word_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND file_type='word'").fetchone()[0]),
                "spreadsheet_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND file_type='spreadsheet'").fetchone()[0]),
                "image_documents": int(connection.execute("SELECT count(*) FROM documents WHERE status='ready' AND file_type='image'").fetchone()[0]),
            }
