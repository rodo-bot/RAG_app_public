import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw

from ragkb.db import KnowledgeDB
from ragkb.extractors import extract_image, extract_word, extract_workbook
from ragkb.indexer import index_library
from ragkb.search import KnowledgeSearch


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        workspace_tmp = Path(__file__).resolve().parents[1] / ".test-artifacts"
        workspace_tmp.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=workspace_tmp)
        self.root = Path(self.temp.name) / "Sync Library"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _make_word(self) -> Path:
        path = self.root / "Operations Notes.docx"
        document = Document()
        document.add_heading("Chlorine Pump", level=1)
        document.add_paragraph("Inspect equipment tag P-410 before startup.")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Alarm"
        table.cell(0, 1).text = "Setpoint"
        table.cell(1, 0).text = "High pressure"
        table.cell(1, 1).text = "85 psi"
        document.save(path)
        return path

    def _make_workbook(self) -> Path:
        path = self.root / "Project Budget.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Cost Summary"
        sheet["A1"] = "Description"
        sheet["B1"] = "Amount"
        sheet["A2"] = "Control panel"
        sheet["B2"] = 12500
        sheet["B3"] = "=SUM(B2:B2)"
        workbook.save(path)
        return path

    def _make_image(self) -> Path:
        path = self.root / "Site Markup.jpg"
        image = Image.new("RGB", (640, 420), "white")
        ImageDraw.Draw(image).text((40, 60), "VALVE V-220", fill="black")
        image.save(path)
        return path

    def test_word_extractor_preserves_headings_and_tables(self):
        units = extract_word(self._make_word())
        self.assertEqual(units[0].page_type, "word_section")
        self.assertIn("Chlorine Pump", units[0].embedded_text)
        self.assertIn("High pressure", units[0].embedded_text)
        self.assertIsNotNone(units[0].preview)

    def test_workbook_extractor_preserves_sheet_cells_and_formulas(self):
        units = extract_workbook(self._make_workbook())
        self.assertEqual(units[0].source_label, "Sheet: Cost Summary, rows 1-3")
        self.assertIn("A2: Control panel", units[0].embedded_text)
        self.assertIn("=SUM(B2:B2)", units[0].embedded_text)

    def test_image_extractor_preserves_visual_without_ocr(self):
        units = extract_image(self._make_image(), enable_ocr=False)
        self.assertEqual(units[0].page_type, "image")
        self.assertEqual(units[0].metadata["pixel_width"], 640)
        self.assertEqual(units[0].text_source, "image_only")
        self.assertIsNotNone(units[0].preview)

    def test_mixed_library_indexes_and_searches_all_new_types(self):
        self._make_word()
        self._make_workbook()
        self._make_image()
        db = KnowledgeDB(Path(self.temp.name) / "knowledge.db")
        preview_root = Path(self.temp.name) / "previews"
        thumbnail_root = Path(self.temp.name) / "thumbnails"
        with (
            patch("ragkb.indexer.PREVIEW_DIR", preview_root),
            patch("ragkb.indexer.THUMBNAIL_DIR", thumbnail_root),
            patch("ragkb.indexer.APP_ROOT", Path(self.temp.name)),
        ):
            report = index_library(self.root, db=db, enable_ocr=False)

        self.assertEqual(report.discovered, 3)
        self.assertEqual(report.indexed, 3)
        self.assertEqual(report.failed, 0)
        documents = {row["file_type"] for row in db.list_document_records()}
        self.assertEqual(documents, {"word", "spreadsheet", "image"})
        search = KnowledgeSearch(db)
        self.assertEqual(search.search("high pressure")[0]["file_type"], "word")
        spreadsheet = search.search("control panel amount")[0]
        self.assertEqual(spreadsheet["file_type"], "spreadsheet")
        self.assertIn("Cost Summary", spreadsheet["source_label"])


if __name__ == "__main__":
    unittest.main()
