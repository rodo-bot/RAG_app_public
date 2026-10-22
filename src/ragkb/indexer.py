from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pypdfium2 as pdfium
import numpy as np
from PIL import Image
from pypdf import PdfReader

from .db import KnowledgeDB
from .extractors import SUPPORTED_EXTENSIONS, extract_non_pdf, file_type_for
from .ocr import find_tesseract, ocr_bitmap
from .paths import APP_ROOT, DATA_DIR, PREVIEW_DIR, SYNC_LIBRARY_DIR, THUMBNAIL_DIR, ensure_data_dirs
from .rag_store import MODEL_NAME, RAGDB
from .text import clean_text, detect_entities, search_variants
from .versions import DocumentVersion, detect_document_version


LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], None]
PAGE_BATCH_SIZE = 32
WEBP_METHOD = 1


def _add_time(timings: dict[str, float] | None, stage: str, started: float) -> None:
    if timings is not None:
        timings[stage] = timings.get(stage, 0.0) + time.perf_counter() - started


def _flush_pages(db: KnowledgeDB, document_id: int, name: str, pending: list[tuple[dict, list]]) -> None:
    if not pending:
        return
    with db.connect() as connection:
        for record, entities in pending:
            db.add_page(document_id, name, record, entities, connection=connection)
    pending.clear()


@dataclass
class IndexReport:
    discovered: int = 0
    indexed: int = 0
    skipped: int = 0
    relocated: int = 0
    removed: int = 0
    failed: int = 0
    pages: int = 0
    embedded_documents: int = 0
    embedded_chunks: int = 0
    timings_seconds: dict[str, float] = field(default_factory=dict)
    slow_files: list[dict] = field(default_factory=list)
    embedding_backend: str = "not_used"
    errors: list[str] = field(default_factory=list)
    removed_documents: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "relocated": self.relocated,
            "removed": self.removed,
            "failed": self.failed,
            "pages": self.pages,
            "embedded_documents": self.embedded_documents,
            "embedded_chunks": self.embedded_chunks,
            "timings_seconds": {key: round(value, 2) for key, value in self.timings_seconds.items()},
            "slow_files": self.slow_files,
            "embedding_backend": self.embedding_backend,
            "errors": self.errors,
            "removed_documents": self.removed_documents,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_files(root: Path) -> list[Path]:
    root = root.resolve()
    data_root = DATA_DIR.resolve()
    if root == data_root or data_root in root.parents or "tmp" in {part.lower() for part in root.parts}:
        return []
    results: list[Path] = []
    # scandir-backed walking avoids resolving and statting every OneDrive file
    # before the unchanged-file check; only symbolic links need resolution.
    for directory, subfolders, filenames in os.walk(root, followlinks=False):
        subfolders[:] = [
            name for name in subfolders
            if name.lower() != "tmp" and Path(directory, name) != data_root
        ]
        for name in filenames:
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            path = Path(directory, name)
            if path.is_symlink():
                path = path.resolve()
            if data_root in path.parents or "tmp" in {part.lower() for part in path.parts}:
                continue
            results.append(path)
    return sorted(results, key=lambda value: str(value).lower())


discover_pdfs = discover_files


def _count_page_images(page) -> int:
    try:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") or {}
    except Exception:
        return 0
    count = 0
    for obj in xobjects.values():
        try:
            count += int(obj.get_object().get("/Subtype") == "/Image")
        except Exception:
            continue
    return count


def _red_markup_score(image: Image.Image) -> float:
    sample = image.copy()
    sample.thumbnail((900, 900))
    pixels = np.asarray(sample.convert("RGB"), dtype=np.int16)
    colored = (pixels.max(axis=2) - pixels.min(axis=2)) > 35
    colored_pixels = int(np.count_nonzero(colored))
    if not colored_pixels:
        return 0.0
    red_pixels = int(np.count_nonzero(
        colored & (pixels[:, :, 0] > 145)
        & (pixels[:, :, 0] > pixels[:, :, 1] * 1.35)
        & (pixels[:, :, 0] > pixels[:, :, 2] * 1.25)
    ))
    return round(red_pixels / colored_pixels, 4)


def _classify_page(text: str, width: float, height: float, image_count: int, embedded_char_count: int = 0) -> str:
    cleaned = clean_text(text)
    chars = len(cleaned)
    words = cleaned.lower().split()
    landscape = width > height * 1.12
    table_terms = sum(words.count(term) for term in ("channel", "alarm", "control", "monitoring", "description", "module"))
    drawing_terms = sum(words.count(term) for term in ("drawing", "sheet", "revision", "legend", "panel", "wiring"))
    if chars == 0:
        return "scanned_drawing" if landscape else "scanned_page"
    if landscape and embedded_char_count < 350:
        return "engineering_drawing"
    if table_terms >= 8 or (chars > 1500 and landscape):
        return "table_or_schedule"
    if landscape and (chars < 1400 or drawing_terms >= 3):
        return "engineering_drawing"
    if chars >= 700:
        return "narrative"
    if image_count and chars < 300:
        return "mixed_or_drawing"
    return "mixed_page"


def _save_rendered_page(pdf_page, preview_path: Path, thumbnail_path: Path, scale: float = 1.5) -> Image.Image:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    image = pdf_page.render(scale=scale).to_pil().convert("RGB")
    image.save(preview_path, format="WEBP", quality=86, method=WEBP_METHOD)
    thumbnail = image.copy()
    thumbnail.thumbnail((420, 320))
    thumbnail.save(thumbnail_path, format="WEBP", quality=80, method=WEBP_METHOD)
    return image


def _relative(path: Path) -> str:
    return path.resolve().relative_to(APP_ROOT.resolve()).as_posix()


def _version_values(version: DocumentVersion) -> tuple[str, str, str, int, bool]:
    return (
        version.relative_path,
        version.family_key,
        version.revision_label,
        version.revision_rank,
        version.version_detected,
    )


def _remove_generated_assets(relative_paths: Iterable[str]) -> None:
    allowed_roots = (PREVIEW_DIR.resolve(), THUMBNAIL_DIR.resolve())
    directories: set[Path] = set()
    for relative in relative_paths:
        candidate = (APP_ROOT / relative).resolve()
        for root in allowed_roots:
            if root in candidate.parents and candidate.parent != root:
                directories.add(candidate.parent)
                break
    for directory in directories:
        if directory.exists():
            def retry_readonly(function, value, _error):
                try:
                    os.chmod(value, stat.S_IWRITE)
                    function(value)
                except OSError as retry_error:
                    LOGGER.warning("Could not remove generated asset %s: %s", value, retry_error)

            shutil.rmtree(directory, onexc=retry_readonly)


def index_pdf(
    pdf_path: Path,
    db: KnowledgeDB,
    force: bool = False,
    enable_ocr: bool = True,
    progress: ProgressCallback | None = None,
    library_root: Path = SYNC_LIBRARY_DIR,
    timings: dict[str, float] | None = None,
) -> tuple[str, int]:
    pdf_path = pdf_path.resolve()
    stat = pdf_path.stat()
    version = detect_document_version(pdf_path, library_root)
    version_values = _version_values(version)
    existing = db.get_document_by_path(pdf_path)
    if existing and not force and existing["status"] == "ready" and existing["mtime_ns"] == stat.st_mtime_ns and existing["size_bytes"] == stat.st_size:
        db.update_document_version(pdf_path, *version_values)
        return "skipped", int(existing["page_count"])

    started = time.perf_counter()
    digest = sha256_file(pdf_path)
    _add_time(timings, "hash", started)
    if existing and not force and existing["status"] == "ready" and existing["sha256"] == digest:
        db.relocate_document(int(existing["id"]), pdf_path, stat.st_size, stat.st_mtime_ns, *version_values)
        return "skipped", int(existing["page_count"])

    if not existing and not force:
        relocated = db.find_relocatable_document(digest, pdf_path.name)
        if relocated:
            db.relocate_document(int(relocated["id"]), pdf_path, stat.st_size, stat.st_mtime_ns, *version_values)
            return "relocated", int(relocated["page_count"])

    document_id = db.upsert_document(pdf_path, digest, stat.st_size, stat.st_mtime_ns, *version_values)
    old_assets = db.get_document_asset_paths(document_id)
    db.clear_document_pages(document_id)
    _remove_generated_assets(old_assets)
    doc_key = f"{document_id:06d}-{digest[:12]}"
    preview_root = PREVIEW_DIR / doc_key
    thumbnail_root = THUMBNAIL_DIR / doc_key
    reader = None
    rendered = None
    pending: list[tuple[dict, list]] = []
    try:
        reader = PdfReader(str(pdf_path))
        rendered = pdfium.PdfDocument(str(pdf_path))
        page_count = len(reader.pages)
        if len(rendered) != page_count:
            raise RuntimeError(f"Reader/render page-count mismatch: {page_count} vs {len(rendered)}")
        for index, page in enumerate(reader.pages):
            page_number = index + 1
            pdf_page = rendered[index]
            if progress:
                progress({"event": "page", "document": pdf_path.name, "page": page_number, "page_count": page_count})
            started = time.perf_counter()
            image_count = _count_page_images(page)
            try:
                text_page = pdf_page.get_textpage()
                try:
                    embedded_text = clean_text(text_page.get_text_range())
                finally:
                    text_page.close()
            except Exception as exc:
                LOGGER.warning("PDFium text extraction failed for %s page %s: %s", pdf_path, page_number, exc)
                embedded_text = ""
            if not embedded_text and image_count == 0:
                # Keep pypdf as a fallback for unusual embedded text encodings.
                try:
                    embedded_text = clean_text(page.extract_text() or "")
                except Exception as exc:
                    LOGGER.warning("pypdf fallback failed for %s page %s: %s", pdf_path, page_number, exc)
            media_box = page.mediabox
            width = float(media_box.width)
            height = float(media_box.height)
            rotation = int(getattr(page, "rotation", 0) or 0) % 360
            if rotation in (90, 270):
                width, height = height, width
            _add_time(timings, "text_extraction", started)
            preview_path = preview_root / f"page-{page_number:04d}.webp"
            thumbnail_path = thumbnail_root / f"page-{page_number:04d}.webp"
            started = time.perf_counter()
            preview_image = _save_rendered_page(pdf_page, preview_path, thumbnail_path)
            red_score = _red_markup_score(preview_image)
            _add_time(timings, "render_and_preview", started)

            ocr_text = ""
            ocr_confidence = 0.0
            started = time.perf_counter()
            should_ocr = enable_ocr and find_tesseract() is not None and (len(embedded_text) < 350 or image_count > 0 and len(embedded_text) < 800)
            if should_ocr:
                ocr_image_bitmap = pdf_page.render(scale=3.0).to_pil().convert("RGB")
                ocr_text, ocr_confidence = ocr_bitmap(ocr_image_bitmap)
                ocr_text = clean_text(ocr_text)
            _add_time(timings, "ocr", started)

            combined_text = clean_text("\n".join(value for value in (embedded_text, ocr_text) if value))
            page_type = _classify_page(combined_text, width, height, image_count, len(embedded_text))
            if embedded_text and ocr_text:
                text_source = "embedded+ocr"
            elif embedded_text:
                text_source = "embedded"
            elif ocr_text:
                text_source = "ocr"
            else:
                text_source = "none"
            confidence = 0.96 if len(embedded_text) >= 350 else max(ocr_confidence, 0.55 if embedded_text else 0.0)
            searchable = search_variants(f"{pdf_path.name}\nPage {page_number}\n{combined_text}")
            record = {
                "page_number": page_number,
                "page_type": page_type,
                "text_source": text_source,
                "embedded_text": embedded_text,
                "ocr_text": ocr_text,
                "search_text": searchable,
                "char_count": len(combined_text),
                "word_count": len(combined_text.split()),
                "image_count": image_count,
                "width_points": width,
                "height_points": height,
                "confidence": confidence,
                "red_markup_score": red_score,
                "preview_path": _relative(preview_path),
                "thumbnail_path": _relative(thumbnail_path),
                "metadata": {"ocr_attempted": should_ocr, "has_possible_red_markup": red_score >= 0.03},
                "source_label": f"Page {page_number}",
            }
            pending.append((record, detect_entities(combined_text)))
            pdf_page.close()
            if len(pending) >= PAGE_BATCH_SIZE:
                started = time.perf_counter()
                _flush_pages(db, document_id, pdf_path.name, pending)
                _add_time(timings, "database_write", started)
        started = time.perf_counter()
        _flush_pages(db, document_id, pdf_path.name, pending)
        db.finish_document(document_id, page_count)
        _add_time(timings, "database_write", started)
        return "indexed", page_count
    except Exception as exc:
        db.fail_document(document_id, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if rendered is not None:
            rendered.close()


def _save_image_page(image: Image.Image, preview_path: Path, thumbnail_path: Path) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    preview = image.convert("RGB")
    preview.save(preview_path, format="WEBP", quality=88, method=WEBP_METHOD)
    thumbnail = preview.copy()
    thumbnail.thumbnail((420, 320))
    thumbnail.save(thumbnail_path, format="WEBP", quality=82, method=WEBP_METHOD)


def index_non_pdf(
    source_path: Path,
    db: KnowledgeDB,
    force: bool = False,
    enable_ocr: bool = True,
    progress: ProgressCallback | None = None,
    library_root: Path = SYNC_LIBRARY_DIR,
    timings: dict[str, float] | None = None,
) -> tuple[str, int]:
    source_path = source_path.resolve()
    source_type = file_type_for(source_path)
    if source_type not in {"word", "spreadsheet", "image"}:
        raise ValueError(f"Unsupported file type: {source_path.suffix}")
    stat = source_path.stat()
    version = detect_document_version(source_path, library_root)
    version_values = _version_values(version)
    existing = db.get_document_by_path(source_path)
    if existing and not force and existing["status"] == "ready" and existing["mtime_ns"] == stat.st_mtime_ns and existing["size_bytes"] == stat.st_size:
        db.update_document_version(source_path, *version_values, source_type)
        return "skipped", int(existing["page_count"])

    started = time.perf_counter()
    digest = sha256_file(source_path)
    _add_time(timings, "hash", started)
    if existing and not force and existing["status"] == "ready" and existing["sha256"] == digest:
        db.relocate_document(int(existing["id"]), source_path, stat.st_size, stat.st_mtime_ns, *version_values, source_type)
        return "skipped", int(existing["page_count"])

    if not existing and not force:
        relocated = db.find_relocatable_document(digest, source_path.name)
        if relocated:
            db.relocate_document(int(relocated["id"]), source_path, stat.st_size, stat.st_mtime_ns, *version_values, source_type)
            return "relocated", int(relocated["page_count"])

    document_id = db.upsert_document(
        source_path,
        digest,
        stat.st_size,
        stat.st_mtime_ns,
        *version_values,
        source_type,
    )
    old_assets = db.get_document_asset_paths(document_id)
    db.clear_document_pages(document_id)
    _remove_generated_assets(old_assets)
    doc_key = f"{document_id:06d}-{digest[:12]}"
    preview_root = PREVIEW_DIR / doc_key
    thumbnail_root = THUMBNAIL_DIR / doc_key
    pending: list[tuple[dict, list]] = []
    try:
        started = time.perf_counter()
        units = extract_non_pdf(source_path, enable_ocr=enable_ocr)
        _add_time(timings, "office_or_image_extraction", started)
        page_count = len(units)
        for index, unit in enumerate(units, start=1):
            if progress:
                progress({"event": "page", "document": source_path.name, "page": index, "page_count": page_count, "source_label": unit.source_label})
            preview_path = preview_root / f"page-{index:04d}.webp"
            thumbnail_path = thumbnail_root / f"page-{index:04d}.webp"
            if unit.preview is None:
                raise RuntimeError(f"No preview generated for {unit.source_label}")
            started = time.perf_counter()
            _save_image_page(unit.preview, preview_path, thumbnail_path)
            red_score = _red_markup_score(unit.preview)
            _add_time(timings, "render_and_preview", started)
            combined_text = clean_text("\n".join(value for value in (unit.embedded_text, unit.ocr_text) if value))
            searchable = search_variants(
                f"{source_path.name}\n{unit.source_label}\n{combined_text}"
            )
            width, height = unit.preview.size
            record = {
                "page_number": index,
                "page_type": unit.page_type,
                "text_source": unit.text_source,
                "embedded_text": unit.embedded_text,
                "ocr_text": unit.ocr_text,
                "search_text": searchable,
                "char_count": len(combined_text),
                "word_count": len(combined_text.split()),
                "image_count": unit.image_count,
                "width_points": float(width),
                "height_points": float(height),
                "confidence": unit.confidence,
                "red_markup_score": red_score,
                "preview_path": _relative(preview_path),
                "thumbnail_path": _relative(thumbnail_path),
                "metadata": {**unit.metadata, "has_possible_red_markup": red_score >= 0.03},
                "source_label": unit.source_label,
            }
            pending.append((record, detect_entities(combined_text)))
            if len(pending) >= PAGE_BATCH_SIZE:
                started = time.perf_counter()
                _flush_pages(db, document_id, source_path.name, pending)
                _add_time(timings, "database_write", started)
        started = time.perf_counter()
        _flush_pages(db, document_id, source_path.name, pending)
        db.finish_document(document_id, page_count)
        _add_time(timings, "database_write", started)
        return "indexed", page_count
    except Exception as exc:
        db.fail_document(document_id, f"{type(exc).__name__}: {exc}")
        raise


def index_file(
    source_path: Path,
    db: KnowledgeDB,
    force: bool = False,
    enable_ocr: bool = True,
    progress: ProgressCallback | None = None,
    library_root: Path = SYNC_LIBRARY_DIR,
    timings: dict[str, float] | None = None,
) -> tuple[str, int]:
    if file_type_for(source_path) == "pdf":
        return index_pdf(source_path, db, force, enable_ocr, progress, library_root, timings)
    return index_non_pdf(source_path, db, force, enable_ocr, progress, library_root, timings)


def index_library(
    root: Path,
    db: KnowledgeDB | None = None,
    force: bool = False,
    enable_ocr: bool = True,
    progress: ProgressCallback | None = None,
) -> IndexReport:
    sync_started = time.perf_counter()
    ensure_data_dirs()
    db = db or RAGDB()
    report = IndexReport()
    scan_started = time.perf_counter()
    sources = discover_files(root)
    _add_time(report.timings_seconds, "scan", scan_started)
    report.discovered = len(sources)
    records = db.list_document_records()
    records_by_path = {str(row["path"]).casefold(): row for row in records}
    embedding_state = db.embedding_state_map() if isinstance(db, RAGDB) else {}
    completed_files = 0
    refresh_versions = False
    if progress:
        progress({"event": "scan", "total_files": len(sources), "completed_files": 0})
    for source_path in sources:
        status = "failed"
        file_started = time.perf_counter()
        file_timings: dict[str, float] = {}
        page_count = 0
        if progress:
            progress({
                "event": "document", "document": source_path.name,
                "total_files": len(sources), "completed_files": completed_files,
            })
        try:
            existing = records_by_path.get(str(source_path).casefold())
            source_stat = source_path.stat()

            def file_progress(event: dict) -> None:
                if progress:
                    progress({
                        **event, "total_files": len(sources),
                        "completed_files": completed_files,
                    })

            if (
                not force and existing is not None and existing["status"] == "ready"
                and existing["mtime_ns"] == source_stat.st_mtime_ns
                and existing["size_bytes"] == source_stat.st_size
            ):
                status, page_count = "skipped", int(existing["page_count"])
            else:
                refresh_versions = True
                started = time.perf_counter()
                status, page_count = index_file(
                    source_path,
                    db,
                    force=force,
                    enable_ocr=enable_ocr,
                    progress=file_progress if progress else None,
                    library_root=root,
                    timings=file_timings,
                )
                _add_time(file_timings, "index_total", started)
            if isinstance(db, RAGDB):
                already_embedded = (
                    status == "skipped" and existing is not None
                    and embedding_state.get(int(existing["id"])) == (existing["sha256"], MODEL_NAME)
                )
                if not already_embedded:
                    current = db.get_document_by_path(source_path)
                    if current is not None and current["status"] == "ready" and db.document_needs_embedding(
                        int(current["id"]), current["sha256"]
                    ):
                        started = time.perf_counter()
                        chunks = db.embed_document(
                            int(current["id"]), progress=file_progress if progress else None,
                            timings=file_timings,
                        )
                        _add_time(file_timings, "embedding_total", started)
                        report.embedded_documents += 1
                        report.embedded_chunks += chunks
                        report.embedding_backend = db.embedding_backend
            report.pages += page_count
            if status == "indexed":
                report.indexed += 1
            elif status == "relocated":
                report.relocated += 1
            else:
                report.skipped += 1
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{source_path.name}: {type(exc).__name__}: {exc}")
            LOGGER.exception("Failed to index %s", source_path)
        finally:
            for stage, duration in file_timings.items():
                report.timings_seconds[stage] = report.timings_seconds.get(stage, 0.0) + duration
            elapsed = time.perf_counter() - file_started
            if elapsed >= 10 and status != "skipped":
                report.slow_files.append({
                    "document": source_path.name,
                    "pages": page_count,
                    "seconds": round(elapsed, 1),
                    "stages": {key: round(value, 1) for key, value in file_timings.items()},
                })
                report.slow_files.sort(key=lambda item: item["seconds"], reverse=True)
                del report.slow_files[10:]
            completed_files += 1
            if progress:
                progress({
                    "event": "file_complete", "document": source_path.name,
                    "status": status, "total_files": len(sources),
                    "completed_files": completed_files,
                })
    discovered_paths = {str(path).casefold() for path in sources}
    # A processed file may have relocated an existing record to its new path.
    # Refresh only in that case so cleanup never deletes a moved document.
    cleanup_records = db.list_document_records() if refresh_versions else records
    for document in cleanup_records:
        if str(document["path"]).casefold() in discovered_paths:
            continue
        if progress:
            progress({
                "event": "removed", "document": document["name"],
                "total_files": len(sources), "completed_files": completed_files,
            })
        assets = db.remove_document(int(document["id"]))
        _remove_generated_assets(assets)
        report.removed += 1
        report.removed_documents.append(document["relative_path"] or document["name"])
        refresh_versions = True
    if refresh_versions:
        db.recompute_current_versions()
    report.timings_seconds["sync_total"] = time.perf_counter() - sync_started
    return report
