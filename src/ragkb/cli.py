from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .indexer import index_library
from .ocr import find_tesseract
from .paths import SYNC_LIBRARY_DIR
from .rag_search import RAGSearch
from .rag_store import RAGDB
from .web import run_web


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only document knowledge base")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index PDFs, Word files, spreadsheets, and images")
    index_parser.add_argument("folder", nargs="?", default=str(SYNC_LIBRARY_DIR))
    index_parser.add_argument("--force", action="store_true")
    index_parser.add_argument("--no-ocr", action="store_true")

    search_parser = subparsers.add_parser("search", help="Search indexed evidence")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)

    web_parser = subparsers.add_parser("web", help="Run the local web interface")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8766)
    web_parser.add_argument("--open", action="store_true")

    subparsers.add_parser("status", help="Show database and OCR status")
    args = parser.parse_args(argv)

    if args.command == "index":
        def progress(event: dict) -> None:
            if event.get("event") == "page":
                print(f"{event['document']}: page {event['page']}/{event['page_count']}")
            else:
                print(f"Indexing {event.get('document')}")
        report = index_library(Path(args.folder), db=RAGDB(), force=args.force, enable_ocr=not args.no_ocr, progress=progress)
        print(json.dumps(report.as_dict(), indent=2))
        return 1 if report.failed else 0
    if args.command == "search":
        print(json.dumps(RAGSearch().search(args.query, limit=args.limit), indent=2, ensure_ascii=False))
        return 0
    if args.command == "web":
        run_web(args.host, args.port, open_browser=args.open)
        return 0
    if args.command == "status":
        print(json.dumps({"stats": RAGDB().stats(), "source_library": str(SYNC_LIBRARY_DIR),
                          "tesseract": str(find_tesseract()) if find_tesseract() else None}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
