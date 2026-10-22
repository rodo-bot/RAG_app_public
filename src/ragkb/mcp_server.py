from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, BinaryIO

from .paths import APP_ROOT, DATA_DIR
from .rag_search import RAGSearch


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "rag-knowledge-base-local", "version": "0.1.0"}


TOOLS = [
    {
        "name": "search_knowledge_base",
        "description": "Search this local RAG index with hybrid exact and semantic retrieval. Returns source locations and evidence for LLM analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Exact tag, phrase, model number, drawing note, or natural-language terms."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
                "page_type": {"type": "string", "description": "Optional page classification filter."},
                "version_scope": {"type": "string", "enum": ["current", "all"], "default": "current", "description": "Search current recognized revisions by default; use all for revision comparisons or history."},
                "mode": {"type": "string", "enum": ["hybrid", "lexical", "semantic"], "default": "hybrid", "description": "Hybrid combines exact and local semantic search."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "get_source_page",
        "description": "Retrieve complete extracted evidence and optional page image for a search result page ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "integer"},
                "include_image": {"type": "boolean", "default": True},
            },
            "required": ["page_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "find_entity",
        "description": "Find every indexed mention of an equipment tag, instrument tag, model, or drawing number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                "version_scope": {"type": "string", "enum": ["current", "all"], "default": "current"},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "list_pdf_documents",
        "description": "List all locally indexed library documents and their processing status. The legacy tool name is retained for compatibility.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "version_scope": {"type": "string", "enum": ["current", "all"], "default": "all", "description": "List every revision by default; use current to show only active versions."}
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "get_document_outline",
        "description": "Get a compact source-location map (PDF pages, Word sections, spreadsheet row ranges, or image frames) for whole-document analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "integer"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "build_analysis_context",
        "description": "Package hybrid retrieved source evidence for a question. The LLM must analyze and cite the sources.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 12},
                "version_scope": {"type": "string", "enum": ["current", "all"], "default": "current", "description": "Use all when the question compares revisions or asks for historical changes."},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
]


class MCPServer:
    def __init__(self, input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None):
        self.input = input_stream or sys.stdin.buffer
        self.output = output_stream or sys.stdout.buffer
        self.search = RAGSearch()
        self.header_framing = False

    def read_message(self) -> dict[str, Any] | None:
        while True:
            first = self.input.readline()
            if not first:
                return None
            if not first.strip():
                continue
            if first.lower().startswith(b"content-length:"):
                self.header_framing = True
                length = int(first.split(b":", 1)[1].strip())
                while True:
                    header = self.input.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                payload = self.input.read(length)
                return json.loads(payload.decode("utf-8"))
            self.header_framing = False
            return json.loads(first.decode("utf-8"))

    def write_message(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if self.header_framing:
            self.output.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
            self.output.write(encoded)
        else:
            self.output.write(encoded + b"\n")
        self.output.flush()

    def run(self) -> None:
        while message := self.read_message():
            response = self.handle(message)
            if response is not None:
                self.write_message(response)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                requested = message.get("params", {}).get("protocolVersion")
                result = {
                    "protocolVersion": requested or PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": "RAG Knowledge Base combines local exact and semantic retrieval. It returns source evidence, not final analysis. For broad questions, call build_analysis_context; for exact identifiers, search_knowledge_base or find_entity. Cite filenames and exact PDF pages, Word sections, spreadsheet rows, or image frames. Inspect source images for drawings, tables, markup, or uncertain OCR. Use version_scope=all for revision history.",
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = message.get("params", {})
                result = self.call_tool(params.get("name", ""), params.get("arguments", {}) or {})
            elif method == "resources/list":
                result = {"resources": []}
            else:
                return self.error(request_id, -32601, f"Method not found: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            return self.error(request_id, -32603, f"{type(exc).__name__}: {exc}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_knowledge_base":
            rows = self.search.search(
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 15)),
                page_type=arguments.get("page_type") or None,
                version_scope=str(arguments.get("version_scope", "current")),
                mode=str(arguments.get("mode", "hybrid")),
            )
            simplified = [
                {
                    "page_id": row["page_id"],
                    "document": row["document_name"],
                    "source_path": row["document_path"],
                    "relative_path": row["relative_path"],
                    "file_type": row["file_type"],
                    "revision_label": row["revision_label"],
                    "is_current": row["is_current"],
                    "page": row["page_number"],
                    "source_location": row["source_label"],
                    "page_type": row["page_type"],
                    "text_source": row["text_source"],
                    "confidence": row["confidence"],
                    "match_type": row["match_type"],
                    "matched_entity": row.get("matched_entity"),
                    "snippet": row["snippet"],
                    "semantic_distance": row.get("semantic_distance"),
                    "retrieval_score": row.get("retrieval_score"),
                }
                for row in rows
            ]
            return self.text_result({"query": arguments.get("query"), "results": simplified})
        if name == "get_source_page":
            page = self.search.get_page(int(arguments["page_id"]))
            if not page:
                return {"isError": True, "content": [{"type": "text", "text": "Page not found"}]}
            payload = {
                "page_id": page["id"],
                "document": page["document_name"],
                "source_path": page["document_path"],
                "relative_path": page["relative_path"],
                "file_type": page["file_type"],
                "revision_label": page["revision_label"],
                "is_current": bool(page["is_current"]),
                "page": page["page_number"],
                "source_location": page["source_label"] or f"Page {page['page_number']}",
                "page_type": page["page_type"],
                "text_source": page["text_source"],
                "confidence": page["confidence"],
                "red_markup_score": page["red_markup_score"],
                "entities": page["entities"],
                "evidence": page["search_text"],
            }
            content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}]
            if arguments.get("include_image", True):
                image_path = self._safe_asset(page["preview_path"])
                if image_path and image_path.exists():
                    content.append({"type": "image", "data": base64.b64encode(image_path.read_bytes()).decode("ascii"), "mimeType": "image/webp"})
            return {"content": content, "structuredContent": payload, "isError": False}
        if name == "find_entity":
            rows = self.search.find_entity(
                str(arguments.get("value", "")),
                int(arguments.get("limit", 50)),
                str(arguments.get("version_scope", "current")),
            )
            return self.text_result({"value": arguments.get("value"), "mentions": rows})
        if name == "list_pdf_documents":
            return self.text_result({"documents": self.search.list_documents(str(arguments.get("version_scope", "all")))})
        if name == "get_document_outline":
            outline = self.search.get_document_outline(int(arguments["document_id"]))
            if not outline:
                return {"isError": True, "content": [{"type": "text", "text": "Document not found"}]}
            return self.text_result(outline)
        if name == "build_analysis_context":
            payload = self.search.build_analysis_context(
                str(arguments.get("question", "")),
                int(arguments.get("limit", 12)),
                str(arguments.get("version_scope", "current")),
            )
            return self.text_result(payload)
        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

    @staticmethod
    def text_result(payload: Any) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        }

    @staticmethod
    def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _safe_asset(relative: str) -> Path | None:
        candidate = (APP_ROOT / relative).resolve()
        root = DATA_DIR.resolve()
        return candidate if root == candidate or root in candidate.parents else None


def main() -> int:
    MCPServer().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
