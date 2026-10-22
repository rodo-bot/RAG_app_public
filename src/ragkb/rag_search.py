from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any

from .rag_store import RAGDB
from .search import KnowledgeSearch
from .text import clean_text


LOGGER = logging.getLogger(__name__)


class RAGSearch(KnowledgeSearch):
    """Fuse exact page search with local semantic chunk search."""

    def __init__(self, db: RAGDB | None = None):
        # Query vectors are tiny; keep search responsive and leave GPU memory
        # available for the optional indexing accelerator.
        super().__init__(db or RAGDB(embedding_device="cpu"))

    def search(
        self,
        query: str,
        limit: int = 20,
        page_type: str | None = None,
        version_scope: str = "current",
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        query = clean_text(query)
        if not query:
            return []
        limit = max(1, min(int(limit), 100))
        mode = str(mode).lower()
        mode = mode if mode in {"hybrid", "lexical", "semantic"} else "hybrid"
        version_scope = "all" if str(version_scope).lower() == "all" else "current"
        lexical = super().search(query, limit=max(limit * 4, 50), page_type=page_type,
                                 version_scope=version_scope) if mode != "semantic" else []
        if mode == "lexical":
            return lexical[:limit]

        rag_db: RAGDB = self.db  # type: ignore[assignment]
        if not rag_db.has_embeddings():
            return lexical[:limit]
        try:
            query_vector = next(rag_db.embedder.query_embed(query))
            chunks = rag_db.semantic_hits(query_vector, limit=max(limit * 8, 80))
        except Exception as exc:
            if mode == "semantic":
                raise
            LOGGER.warning("Semantic search unavailable; using lexical results: %s", exc)
            return lexical[:limit]
        semantic: dict[int, dict[str, Any]] = {}
        for rank, chunk in enumerate(chunks, start=1):
            if version_scope != "all" and not chunk["is_current"]:
                continue
            if page_type and chunk["page_type"] != page_type:
                continue
            semantic.setdefault(int(chunk["page_id"]), {**chunk, "rank": rank})

        if mode == "semantic":
            ordered_ids = list(semantic)
        else:
            lexical_ids = [int(item["page_id"]) for item in lexical]
            ordered_ids = list(dict.fromkeys(lexical_ids + list(semantic)))
        if not ordered_ids:
            return lexical[:limit]

        lexical_by_page = {int(item["page_id"]): item for item in lexical}
        lexical_rank = {int(item["page_id"]): rank for rank, item in enumerate(lexical, start=1)}
        results: list[dict[str, Any]] = []
        for page_id in ordered_ids:
            lexical_item = lexical_by_page.get(page_id)
            chunk = semantic.get(page_id)
            if lexical_item is not None:
                item = dict(lexical_item)
            else:
                page = self.get_page(page_id)
                if page is None:
                    continue
                item = self._row_result(page, query, 0.0, "semantic")
                item["snippet"] = chunk["content"][:360] if chunk else item["snippet"]
            fused = 0.0
            if page_id in lexical_rank:
                fused += 1.0 / (60 + lexical_rank[page_id])
                if "exact_entity" in item["match_type"]:
                    fused += 0.02
            if chunk is not None:
                fused += 1.0 / (60 + chunk["rank"])
                item["semantic_distance"] = chunk["distance"]
                item["matched_chunk"] = chunk["content"][:500]
                if lexical_item is not None:
                    item["match_type"] = "hybrid" if "exact_entity" not in item["match_type"] else "exact_entity+hybrid"
            item["retrieval_score"] = fused
            results.append(item)
        results.sort(key=lambda item: (-item["retrieval_score"], item["document_name"], item["page_number"]))
        selected: list[dict[str, Any]] = []
        per_document: dict[int, int] = defaultdict(int)
        for item in results:
            if per_document[item["document_id"]] < 3:
                selected.append(item)
                per_document[item["document_id"]] += 1
            if len(selected) >= limit:
                return selected
        selected_ids = {item["page_id"] for item in selected}
        selected.extend(item for item in results if item["page_id"] not in selected_ids)
        return selected[:limit]
