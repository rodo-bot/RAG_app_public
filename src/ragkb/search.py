from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import KnowledgeDB
from .text import clean_text, fts_query, normalize_identifier, query_tokens


QUERY_STOP_WORDS = {
    "about", "after", "also", "and", "are", "can", "could", "does", "for", "from",
    "give", "how", "into", "its", "make", "of", "on", "or", "please", "should",
    "show", "summarize", "summary", "tell", "that", "the", "their", "this", "to",
    "what", "when", "where", "which", "with", "would", "you",
}


def _snippet(text: str, query: str, length: int = 360) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= length:
        return cleaned
    lowered = cleaned.lower()
    positions = [lowered.find(token.lower()) for token in query_tokens(query)]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - length // 3)
    end = min(len(cleaned), start + length)
    prefix = "..." if start else ""
    suffix = "..." if end < len(cleaned) else ""
    return prefix + cleaned[start:end].strip() + suffix


class KnowledgeSearch:
    def __init__(self, db: KnowledgeDB | None = None):
        self.db = db or KnowledgeDB()

    def search(
        self,
        query: str,
        limit: int = 20,
        page_type: str | None = None,
        version_scope: str = "current",
    ) -> list[dict[str, Any]]:
        query = clean_text(query)
        if not query:
            return []
        limit = max(1, min(int(limit), 100))
        expression = fts_query(query)
        results: dict[int, dict[str, Any]] = {}
        version_scope = "all" if str(version_scope).lower() == "all" else "current"
        filter_clause = " AND p.page_type=?" if page_type else ""
        if version_scope == "current":
            filter_clause += " AND d.is_current=1"
        parameters: list[Any] = [expression]
        if page_type:
            parameters.append(page_type)
        parameters.append(limit * 3)
        sql = f"""
            SELECT p.*, d.name AS document_name, d.path AS document_path,
                   d.relative_path,d.family_key,d.revision_label,d.revision_rank,
                   d.version_detected,d.is_current,d.file_type,bm25(pages_fts) AS rank
            FROM pages_fts
            JOIN pages p ON p.id=pages_fts.page_id
            JOIN documents d ON d.id=p.document_id
            WHERE pages_fts MATCH ? {filter_clause}
            ORDER BY rank
            LIMIT ?
        """
        with self.db.connect() as connection:
            try:
                rows = connection.execute(sql, parameters).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                results[int(row["id"])] = self._row_result(row, query, float(row["rank"]), "full_text")

            # Natural questions often contain words that will not all occur verbatim on one
            # engineering page. If strict FTS finds nothing, retrieve pages matching the
            # meaningful terms so the LLM still receives evidence to reason over.
            meaningful_tokens = []
            for token in query_tokens(query):
                lowered = token.lower()
                if len(lowered) >= 3 and lowered not in QUERY_STOP_WORDS and lowered not in meaningful_tokens:
                    meaningful_tokens.append(lowered)
            if not rows and len(meaningful_tokens) >= 2:
                any_expression = " OR ".join(f'"{token}"' for token in meaningful_tokens)
                broad_parameters: list[Any] = [any_expression]
                if page_type:
                    broad_parameters.append(page_type)
                broad_parameters.append(limit * 4)
                try:
                    broad_rows = connection.execute(sql, broad_parameters).fetchall()
                except sqlite3.OperationalError:
                    broad_rows = []
                for row in broad_rows:
                    page_id = int(row["id"])
                    if page_id in results:
                        continue
                    lowered_text = str(row["search_text"]).lower()
                    matched = sum(token in lowered_text for token in meaningful_tokens)
                    coverage = matched / len(meaningful_tokens)
                    item = self._row_result(row, query, float(row["rank"]) + 8.0 - (coverage * 6.0), "keyword_evidence")
                    item["query_term_coverage"] = round(coverage, 3)
                    results[page_id] = item

            normalized = normalize_identifier(query)
            if len(normalized) >= 4:
                entity_filter = " AND d.is_current=1" if version_scope == "current" else ""
                entity_rows = connection.execute(
                    f"""
                    SELECT p.*, d.name AS document_name, d.path AS document_path,
                           d.relative_path,d.family_key,d.revision_label,d.revision_rank,
                           d.version_detected,d.is_current,d.file_type,
                           e.display_value, e.normalized_value, e.entity_type, m.context
                    FROM entities e
                    JOIN mentions m ON m.entity_id=e.id
                    JOIN pages p ON p.id=m.page_id
                    JOIN documents d ON d.id=p.document_id
                    WHERE e.normalized_value LIKE ? {entity_filter}
                    ORDER BY CASE WHEN e.normalized_value=? THEN 0 ELSE 1 END, p.page_number
                    LIMIT ?
                    """,
                    (f"%{normalized}%", normalized, limit * 2),
                ).fetchall()
                for row in entity_rows:
                    page_id = int(row["id"])
                    if page_type and row["page_type"] != page_type:
                        continue
                    existing = results.get(page_id)
                    if existing:
                        existing["match_type"] = "exact_entity+full_text"
                        existing["matched_entity"] = row["display_value"]
                        existing["score"] -= 10
                    else:
                        item = self._row_result(row, query, -20.0, "exact_entity")
                        item["matched_entity"] = row["display_value"]
                        item["snippet"] = row["context"] or item["snippet"]
                        results[page_id] = item
        return sorted(results.values(), key=lambda item: (item["score"], item["document_name"], item["page_number"]))[:limit]

    @staticmethod
    def _row_result(row: sqlite3.Row, query: str, score: float, match_type: str) -> dict[str, Any]:
        return {
            "page_id": int(row["id"]),
            "document_id": int(row["document_id"]),
            "document_name": row["document_name"],
            "document_path": row["document_path"],
            "relative_path": row["relative_path"],
            "family_key": row["family_key"],
            "revision_label": row["revision_label"],
            "revision_rank": int(row["revision_rank"]),
            "version_detected": bool(row["version_detected"]),
            "is_current": bool(row["is_current"]),
            "file_type": row["file_type"],
            "page_number": int(row["page_number"]),
            "source_label": row["source_label"] or f"Page {int(row['page_number'])}",
            "page_type": row["page_type"],
            "text_source": row["text_source"],
            "confidence": float(row["confidence"]),
            "red_markup_score": float(row["red_markup_score"]),
            "preview_path": row["preview_path"],
            "thumbnail_path": row["thumbnail_path"],
            "snippet": _snippet(row["search_text"], query),
            "score": score,
            "match_type": match_type,
        }

    def list_documents(self, version_scope: str = "all") -> list[dict[str, Any]]:
        version_scope = "current" if str(version_scope).lower() == "current" else "all"
        where_clause = "WHERE is_current=1" if version_scope == "current" else ""
        with self.db.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM documents {where_clause} ORDER BY family_key COLLATE NOCASE,revision_rank DESC,name COLLATE NOCASE"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if not document:
                return None
            pages = connection.execute(
                "SELECT id,page_number,source_label,page_type,text_source,char_count,word_count,confidence,red_markup_score,thumbnail_path FROM pages WHERE document_id=? ORDER BY page_number",
                (document_id,),
            ).fetchall()
            result = dict(document)
            result["pages"] = [dict(row) for row in pages]
            return result

    def get_document_outline(self, document_id: int) -> dict[str, Any] | None:
        """Return a compact map that helps an LLM choose pages for deeper inspection."""
        with self.db.connect() as connection:
            document = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if not document:
                return None
            pages = connection.execute(
                """
                SELECT p.id AS page_id,p.page_number,p.source_label,p.page_type,p.text_source,p.word_count,
                       p.confidence,p.red_markup_score,substr(p.search_text,1,420) AS evidence_preview
                FROM pages p
                WHERE p.document_id=?
                ORDER BY p.page_number
                """,
                (document_id,),
            ).fetchall()
            result = dict(document)
            result["pages"] = [dict(page) for page in pages]
            return result

    def build_analysis_context(
        self,
        question: str,
        limit: int = 12,
        version_scope: str = "current",
    ) -> dict[str, Any]:
        """Package retrieved source evidence; the calling LLM performs the analysis."""
        version_scope = "all" if str(version_scope).lower() == "all" else "current"
        matches = self.search(question, limit=max(1, min(limit, 20)), version_scope=version_scope)
        evidence: list[dict[str, Any]] = []
        total_characters = 0
        character_budget = 50000
        for match in matches:
            page = self.get_page(match["page_id"])
            if not page:
                continue
            remaining = character_budget - total_characters
            if remaining <= 0:
                break
            page_text = clean_text(page.get("search_text", ""))[: min(6000, remaining)]
            total_characters += len(page_text)
            evidence.append(
                {
                    "page_id": page["id"],
                    "document": page["document_name"],
                    "source_path": page["document_path"],
                    "relative_path": page["relative_path"],
                    "revision_label": page["revision_label"],
                    "is_current": bool(page["is_current"]),
                    "page": page["page_number"],
                    "source_location": page["source_label"] or f"Page {page['page_number']}",
                    "file_type": page["file_type"],
                    "page_type": page["page_type"],
                    "text_source": page["text_source"],
                    "confidence": page["confidence"],
                    "match_type": match["match_type"],
                    "matched_entity": match.get("matched_entity"),
                    "entities": page.get("entities", []),
                    "evidence": page_text,
                }
            )
        return {
            "question": question,
            "version_scope": version_scope,
            "instruction": "Use this as source evidence. Perform the interpretation, synthesis, recommendations, and summary in the LLM; cite the document and exact source location for every material claim.",
            "evidence_pages": evidence,
            "truncated": total_characters >= character_budget,
        }

    def get_page(self, page_id: int) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT p.*, d.name AS document_name, d.path AS document_path,
                       d.relative_path,d.family_key,d.revision_label,d.revision_rank,
                       d.version_detected,d.is_current,d.file_type
                FROM pages p JOIN documents d ON d.id=p.document_id WHERE p.id=?
                """,
                (page_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            entities = connection.execute(
                """
                SELECT e.entity_type,e.display_value,e.normalized_value,m.context,m.confidence
                FROM mentions m JOIN entities e ON e.id=m.entity_id
                WHERE m.page_id=? ORDER BY e.entity_type,e.display_value
                """,
                (page_id,),
            ).fetchall()
            result["entities"] = [dict(entity) for entity in entities]
            return result

    def find_entity(self, value: str, limit: int = 50, version_scope: str = "current") -> list[dict[str, Any]]:
        normalized = normalize_identifier(value)
        if not normalized:
            return []
        version_scope = "all" if str(version_scope).lower() == "all" else "current"
        version_clause = " AND d.is_current=1" if version_scope == "current" else ""
        with self.db.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT e.entity_type,e.display_value,e.normalized_value,m.context,
                       p.id AS page_id,p.page_number,p.page_type,d.id AS document_id,d.name AS document_name,
                       p.source_label,d.relative_path,d.family_key,d.revision_label,d.revision_rank,
                       d.version_detected,d.is_current,d.file_type
                FROM entities e
                JOIN mentions m ON m.entity_id=e.id
                JOIN pages p ON p.id=m.page_id
                JOIN documents d ON d.id=p.document_id
                WHERE e.normalized_value LIKE ? {version_clause}
                ORDER BY CASE WHEN e.normalized_value=? THEN 0 ELSE 1 END,d.name,p.page_number
                LIMIT ?
                """,
                (f"%{normalized}%", normalized, max(1, min(limit, 100))),
            ).fetchall()
            return [dict(row) for row in rows]
