import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from docx import Document
from pypdf import PdfWriter

from ragkb.indexer import _red_markup_score, index_library
from ragkb.rag_search import RAGSearch
from ragkb.rag_store import RAGDB, split_chunks


class FakeEmbedder:
    def embed(self, texts):
        for text in texts:
            lowered = text.lower()
            vector = np.zeros(384, dtype=np.float32)
            vector[0] = 1.0 if "motor" in lowered or "overload" in lowered else 0.0
            vector[1] = 1.0 if "network" in lowered else 0.0
            yield vector

    def query_embed(self, query):
        return self.embed([query])


class FailingEmbedder:
    def embed(self, _texts):
        raise RuntimeError("simulated GPU failure")


class RAGTests(unittest.TestCase):
    def test_red_markup_score_preserves_color_classification(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (180, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 89, 179), fill=(200, 20, 20))
        draw.rectangle((90, 0, 179, 179), fill=(20, 20, 200))
        self.assertEqual(_red_markup_score(image), 0.5)

    def test_pdf_batch_keeps_all_pages_and_previews(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            library = root / "library"
            library.mkdir()
            source = library / "Many Pages.pdf"
            writer = PdfWriter()
            for _ in range(35):
                writer.add_blank_page(width=200, height=300)
            with source.open("wb") as stream:
                writer.write(stream)
            db = RAGDB(root / "rag.db", embedder=FakeEmbedder())
            with (
                patch("ragkb.indexer.PREVIEW_DIR", root / "previews"),
                patch("ragkb.indexer.THUMBNAIL_DIR", root / "thumbnails"),
                patch("ragkb.indexer.APP_ROOT", root),
            ):
                report = index_library(library, db=db, enable_ocr=False)
            self.assertEqual((report.indexed, report.pages, report.failed), (1, 35, 0))
            self.assertEqual(db.stats()["pages"], 35)
            self.assertEqual(len(list((root / "previews").rglob("*.webp"))), 35)
            self.assertGreater(report.timings_seconds["database_write"], 0)
            self.assertGreater(report.timings_seconds["render_and_preview"], 0)

    def test_gpu_batch_failure_retries_on_cpu_without_losing_document(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            library = root / "library"
            library.mkdir()
            source = library / "Motor.docx"
            document = Document()
            document.add_heading("Motor", 1)
            document.add_paragraph("An overload relay protects the motor.")
            document.save(source)
            db = RAGDB(root / "rag.db", embedder=FailingEmbedder())
            db.embedding_backend = "cuda"
            with (
                patch("ragkb.indexer.PREVIEW_DIR", root / "previews"),
                patch("ragkb.indexer.THUMBNAIL_DIR", root / "thumbnails"),
                patch("ragkb.indexer.APP_ROOT", root),
                patch("ragkb.rag_store.TextEmbedding", side_effect=lambda **_: FakeEmbedder()),
            ):
                report = index_library(library, db=db, enable_ocr=False)
            self.assertEqual((report.failed, report.embedded_documents), (0, 1))
            self.assertEqual(report.embedding_backend, "cpu")
            self.assertEqual(db.stats()["rag_chunks"], 1)

    def test_chunking_preserves_overlap(self):
        words = [f"word{index}" for index in range(240)]
        chunks = split_chunks(" ".join(words))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].split()[-40:], chunks[1].split()[:40])

    def test_sync_search_resync_and_remove(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            library = root / "library"
            library.mkdir()
            source = library / "Motor Manual.docx"
            document = Document()
            document.add_heading("Motor protection", 1)
            document.add_paragraph("An overload relay trips the motor after excess current.")
            document.save(source)
            db = RAGDB(root / "rag.db", embedder=FakeEmbedder())
            preview_root = root / "previews"
            thumbnail_root = root / "thumbnails"
            with (
                patch("ragkb.indexer.PREVIEW_DIR", preview_root),
                patch("ragkb.indexer.THUMBNAIL_DIR", thumbnail_root),
                patch("ragkb.indexer.APP_ROOT", root),
            ):
                first = index_library(library, db=db, enable_ocr=False)
                self.assertEqual((first.indexed, first.embedded_documents), (1, 1))
                self.assertGreater(first.embedded_chunks, 0)
                matches = RAGSearch(db).search("motor fault", mode="semantic")
                self.assertEqual(matches[0]["document_name"], source.name)
                self.assertIn("section", matches[0]["source_label"].lower())

                second = index_library(library, db=db, enable_ocr=False)
                self.assertEqual((second.skipped, second.embedded_documents), (1, 0))
                self.assertEqual(db.stats()["embedded_documents"], 1)

                source.unlink()
                third = index_library(library, db=db, enable_ocr=False)
                self.assertEqual(third.removed, 1)
                self.assertEqual(db.stats()["rag_chunks"], 0)


if __name__ == "__main__":
    unittest.main()
