from __future__ import annotations

import sqlite3
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import sqlite_vec
from fastembed import TextEmbedding

from .db import KnowledgeDB, utc_now
from .paths import DATABASE_PATH, MODEL_DIR, SETTINGS_PATH
from .text import clean_text


MODEL_NAME = "BAAI/bge-small-en-v1.5"
VECTOR_DIMENSIONS = 384
CHUNK_WORDS = 220
CHUNK_OVERLAP = 40
LOGGER = logging.getLogger(__name__)


def _embedding_device() -> str:
    if not SETTINGS_PATH.exists():
        return "auto"
    try:
        value = str(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("embedding_device", "auto")).lower()
    except (OSError, ValueError, TypeError):
        return "auto"
    return value if value in {"auto", "cpu", "cuda"} else "auto"


def split_chunks(text: str) -> list[str]:
    words = clean_text(text).split()
    if not words:
        return []
    step = CHUNK_WORDS - CHUNK_OVERLAP
    return [" ".join(words[start:start + CHUNK_WORDS]) for start in range(0, len(words), step)
            if words[start:start + CHUNK_WORDS]]


class RAGDB(KnowledgeDB):
    """Own SQLite evidence store plus local semantic vectors."""

    def __init__(
        self, path: Path = DATABASE_PATH, embedder: TextEmbedding | None = None,
        embedding_device: str | None = None,
    ):
        self._embedder = embedder
        self._requested_device = embedding_device or _embedding_device()
        self.embedding_backend = "injected" if embedder is not None else "not_loaded"
        self._sqlite_vec_available: bool | None = None
        super().__init__(path)
        self.initialize_vectors()

    @contextmanager
    def vector_connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            if self._sqlite_vec_available is not False:
                enable_extension = getattr(connection, "enable_load_extension", None)
                if enable_extension is None:
                    self._sqlite_vec_available = False
                    LOGGER.warning("SQLite extensions are unavailable; using NumPy vector search")
                else:
                    try:
                        enable_extension(True)
                        sqlite_vec.load(connection)
                        self._sqlite_vec_available = True
                    except (AttributeError, OSError, sqlite3.Error) as exc:
                        self._sqlite_vec_available = False
                        LOGGER.warning("sqlite-vec is unavailable; using NumPy vector search: %s", exc)
                    finally:
                        try:
                            enable_extension(False)
                        except (AttributeError, sqlite3.Error):
                            pass
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def has_embeddings(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM rag_chunks LIMIT 1").fetchone() is not None

    def initialize_vectors(self) -> None:
        with self.vector_connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id INTEGER PRIMARY KEY,
                    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(page_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_page ON rag_chunks(page_id);
                CREATE TABLE IF NOT EXISTS rag_document_state (
                    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                    source_sha256 TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    completed_at TEXT NOT NULL
                );
            """)
            if self._sqlite_vec_available:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors USING "
                    "vec0(embedding float[384] distance_metric=cosine)"
                )
            else:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS rag_vectors_fallback ("
                    "rowid INTEGER PRIMARY KEY, embedding BLOB NOT NULL)"
                )

    @property
    def _vector_table(self) -> str:
        return "rag_vectors" if self._sqlite_vec_available else "rag_vectors_fallback"

    def embedding_state_map(self) -> dict[int, tuple[str, str]]:
        with self.connect() as connection:
            return {
                int(row["document_id"]): (row["source_sha256"], row["model_name"])
                for row in connection.execute(
                    "SELECT document_id,source_sha256,model_name FROM rag_document_state"
                )
            }

    def document_needs_embedding(self, document_id: int, sha256: str) -> bool:
        with self.connect() as connection:
            state = connection.execute(
                "SELECT source_sha256,model_name FROM rag_document_state WHERE document_id=?",
                (document_id,),
            ).fetchone()
        return state is None or state["source_sha256"] != sha256 or state["model_name"] != MODEL_NAME

    @property
    def embedder(self) -> TextEmbedding:
        if self._embedder is None:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            requested = self._requested_device
            if requested in {"auto", "cuda"}:
                try:
                    import onnxruntime as ort
                    if "CUDAExecutionProvider" in ort.get_available_providers():
                        # The optional GPU runtime ships CUDA/cuDNN DLLs in its
                        # Python environment; preload them before ONNX starts.
                        if hasattr(ort, "preload_dlls"):
                            ort.preload_dlls(directory="")
                        candidate = TextEmbedding(
                            model_name=MODEL_NAME, cache_dir=MODEL_DIR,
                            providers=["CUDAExecutionProvider"],
                        )
                        session = getattr(getattr(candidate, "model", None), "model", None)
                        if session is not None and "CUDAExecutionProvider" in session.get_providers():
                            self._embedder = candidate
                            self.embedding_backend = "cuda"
                except Exception as exc:
                    LOGGER.warning("GPU embedding unavailable; using CPU: %s", exc)
                if requested == "cuda" and self._embedder is None:
                    LOGGER.warning("CUDA embedding was requested but is unavailable; using CPU")
            if self._embedder is None:
                self._use_cpu_embedder()
        return self._embedder

    def _use_cpu_embedder(self) -> None:
        self._embedder = TextEmbedding(model_name=MODEL_NAME, cache_dir=MODEL_DIR,
                                       providers=["CPUExecutionProvider"])
        self.embedding_backend = "cpu"

    def _clear_document_embeddings(self, document_id: int) -> None:
        with self.vector_connection() as connection:
            chunk_ids = [
                int(row[0]) for row in connection.execute(
                    "SELECT c.id FROM rag_chunks c JOIN pages p ON p.id=c.page_id WHERE p.document_id=?",
                    (document_id,),
                )
            ]
            connection.executemany(
                f"DELETE FROM {self._vector_table} WHERE rowid=?",
                ((chunk_id,) for chunk_id in chunk_ids),
            )
            connection.execute(
                "DELETE FROM rag_chunks WHERE page_id IN (SELECT id FROM pages WHERE document_id=?)",
                (document_id,),
            )
            connection.execute("DELETE FROM rag_document_state WHERE document_id=?", (document_id,))

    def clear_document_pages(self, document_id: int) -> None:
        self._clear_document_embeddings(document_id)
        super().clear_document_pages(document_id)

    def remove_document(self, document_id: int) -> list[str]:
        self._clear_document_embeddings(document_id)
        return super().remove_document(document_id)

    def embed_document(
        self, document_id: int, progress: Callable[[dict], None] | None = None,
        timings: dict[str, float] | None = None,
    ) -> int:
        with self.connect() as connection:
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if document is None or document["status"] != "ready":
                raise ValueError("Only ready documents can be embedded")
            pages = connection.execute(
                "SELECT id,page_number,source_label,embedded_text,ocr_text FROM pages "
                "WHERE document_id=? ORDER BY page_number", (document_id,),
            ).fetchall()
        self._clear_document_embeddings(document_id)
        batch: list[tuple[int, int, str]] = []
        chunk_count = 0

        def flush() -> None:
            nonlocal chunk_count
            if not batch:
                return
            started = time.perf_counter()
            texts = [item[2] for item in batch]
            try:
                vectors = list(self.embedder.embed(texts))
            except Exception as exc:
                if self.embedding_backend != "cuda":
                    raise
                LOGGER.warning("GPU embedding failed during indexing; retrying batch on CPU: %s", exc)
                self._use_cpu_embedder()
                vectors = list(self.embedder.embed(texts))
            if timings is not None:
                timings["embedding_inference"] = timings.get("embedding_inference", 0.0) + time.perf_counter() - started
            if len(vectors) != len(batch):
                raise RuntimeError("Embedding model returned the wrong number of vectors")
            started = time.perf_counter()
            with self.vector_connection() as connection:
                for (page_id, ordinal, content), vector in zip(batch, vectors, strict=True):
                    packed = np.asarray(vector, dtype=np.float32)
                    if packed.shape != (VECTOR_DIMENSIONS,):
                        raise RuntimeError("Embedding model dimensions changed")
                    cursor = connection.execute(
                        "INSERT INTO rag_chunks(page_id,ordinal,content) VALUES(?,?,?)",
                        (page_id, ordinal, content),
                    )
                    connection.execute(
                        f"INSERT INTO {self._vector_table}(rowid,embedding) VALUES(?,?)",
                        (cursor.lastrowid, packed.tobytes()),
                    )
            if timings is not None:
                timings["vector_write"] = timings.get("vector_write", 0.0) + time.perf_counter() - started
            chunk_count += len(batch)
            batch.clear()

        for position, page in enumerate(pages, start=1):
            body = clean_text(" ".join(part for part in (page["embedded_text"], page["ocr_text"]) if part))
            label = f"{document['relative_path'] or document['name']} {page['source_label'] or 'Page ' + str(page['page_number'])}"
            for ordinal, chunk in enumerate(split_chunks(body)):
                batch.append((int(page["id"]), ordinal, f"{label}. {chunk}"))
                if len(batch) >= 32:
                    flush()
            if progress:
                progress({"event": "embedding", "document": document["name"],
                          "page": position, "page_count": len(pages)})
        flush()
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO rag_document_state(document_id,source_sha256,model_name,chunk_count,completed_at) "
                "VALUES(?,?,?,?,?)",
                (document_id, document["sha256"], MODEL_NAME, chunk_count, utc_now()),
            )
        return chunk_count

    def semantic_hits(self, embedding: np.ndarray, limit: int = 80) -> list[dict]:
        packed = np.asarray(embedding, dtype=np.float32)
        if packed.shape != (VECTOR_DIMENSIONS,):
            raise ValueError("Query embedding has the wrong dimensions")
        with self.vector_connection() as connection:
            result_limit = max(1, min(limit, 200))
            if self._sqlite_vec_available:
                nearest = [
                    (int(row["rowid"]), float(row["distance"]))
                    for row in connection.execute(
                        "SELECT rowid,distance FROM rag_vectors WHERE embedding MATCH ? AND k=?",
                        (packed.tobytes(), result_limit),
                    ).fetchall()
                ]
            else:
                stored = connection.execute(
                    "SELECT rowid,embedding FROM rag_vectors_fallback"
                ).fetchall()
                valid = [
                    (int(row["rowid"]), np.frombuffer(row["embedding"], dtype=np.float32))
                    for row in stored
                    if len(row["embedding"]) == VECTOR_DIMENSIONS * np.dtype(np.float32).itemsize
                ]
                if not valid:
                    return []
                matrix = np.vstack([vector for _, vector in valid])
                denominator = np.linalg.norm(matrix, axis=1) * np.linalg.norm(packed)
                similarity = np.divide(
                    matrix @ packed,
                    denominator,
                    out=np.zeros(len(valid), dtype=np.float32),
                    where=denominator != 0,
                )
                distances = 1.0 - similarity
                nearest = [
                    (valid[int(index)][0], float(distances[int(index)]))
                    for index in np.argsort(distances)[:result_limit]
                ]
            if not nearest:
                return []
            ids = [rowid for rowid, _ in nearest]
            placeholders = ",".join("?" for _ in ids)
            metadata = {
                int(row["id"]): dict(row)
                for row in connection.execute(
                    f"SELECT c.id,c.page_id,c.content,p.page_type,d.is_current "
                    f"FROM rag_chunks c JOIN pages p ON p.id=c.page_id "
                    f"JOIN documents d ON d.id=p.document_id WHERE c.id IN ({placeholders})",
                    ids,
                )
            }
            return [
                {**metadata[rowid], "distance": distance}
                for rowid, distance in nearest
                if rowid in metadata
            ]

    def stats(self) -> dict[str, int]:
        result = super().stats()
        with self.connect() as connection:
            result["embedded_documents"] = int(connection.execute("SELECT count(*) FROM rag_document_state").fetchone()[0])
            result["rag_chunks"] = int(connection.execute("SELECT count(*) FROM rag_chunks").fetchone()[0])
        return result
