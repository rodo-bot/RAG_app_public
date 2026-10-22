import tempfile
import unittest
from pathlib import Path

from ragkb.db import KnowledgeDB
from ragkb.search import KnowledgeSearch
from ragkb.text import detect_entities, search_variants


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = KnowledgeDB(Path(self.temp.name) / "test.db")
        fake_pdf = Path(self.temp.name) / "sample.pdf"
        document_id = self.db.upsert_document(fake_pdf, "abc", 123, 1)
        self.document_id = document_id
        self.fake_pdf = fake_pdf
        content = search_variants("PUMP 1 PHASE FAIL ALARM is monitored at LIT 0101.")
        record = {
            "page_number": 3,
            "page_type": "engineering_drawing",
            "text_source": "embedded",
            "embedded_text": content,
            "ocr_text": "",
            "search_text": content,
            "char_count": len(content),
            "word_count": len(content.split()),
            "image_count": 1,
            "width_points": 1000.0,
            "height_points": 700.0,
            "confidence": 0.9,
            "red_markup_score": 0.1,
            "preview_path": "data/previews/example.webp",
            "thumbnail_path": "data/thumbnails/example.webp",
            "metadata": {},
        }
        self.db.add_page(document_id, fake_pdf.name, record, detect_entities(content))
        self.db.finish_document(document_id, 1)
        self.search = KnowledgeSearch(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_search_finds_phrase_terms(self):
        results = self.search.search("phase fail")
        self.assertEqual(results[0]["page_number"], 3)

    def test_search_finds_compact_tag(self):
        results = self.search.search("LIT0101")
        self.assertEqual(results[0]["match_type"], "exact_entity+full_text")

    def test_natural_question_falls_back_to_keyword_evidence(self):
        results = self.search.search("What equipment monitors the pump alarm condition?")
        self.assertEqual(results[0]["page_number"], 3)
        self.assertEqual(results[0]["match_type"], "keyword_evidence")

    def test_keyword_fallback_rejects_single_generic_term(self):
        results = self.search.search(
            "Audit architecture operational requirements indexing failures duplicate revisions"
        )
        self.assertEqual(results, [])

    def test_keyword_fallback_requires_identifier_when_question_contains_one(self):
        results = self.search.search(
            "Why does ItemErrorCntAlarm come on and off in System Platform?"
        )
        self.assertEqual(results, [])

    def test_build_analysis_context_returns_source_evidence(self):
        payload = self.search.build_analysis_context("Explain the phase fail alarm")
        self.assertEqual(payload["evidence_pages"][0]["page"], 3)
        self.assertIn("LLM", payload["instruction"])
        self.assertIn("LIT 0101", payload["evidence_pages"][0]["evidence"])

    def test_current_scope_hides_superseded_revision(self):
        self.db.update_document_version(
            self.fake_pdf, "Project/Rev A/sample.pdf", "project/sample.pdf", "Rev A", 2001, True
        )
        newer_pdf = Path(self.temp.name) / "newer" / "sample.pdf"
        newer_id = self.db.upsert_document(
            newer_pdf,
            "def",
            456,
            2,
            "Project/Rev B/sample.pdf",
            "project/sample.pdf",
            "Rev B",
            2002,
            True,
        )
        content = search_variants("PUMP 1 PHASE FAIL ALARM revised at LIT 0101.")
        record = {
            "page_number": 4,
            "page_type": "engineering_drawing",
            "text_source": "embedded",
            "embedded_text": content,
            "ocr_text": "",
            "search_text": content,
            "char_count": len(content),
            "word_count": len(content.split()),
            "image_count": 1,
            "width_points": 1000.0,
            "height_points": 700.0,
            "confidence": 0.9,
            "red_markup_score": 0.1,
            "preview_path": "data/previews/newer.webp",
            "thumbnail_path": "data/thumbnails/newer.webp",
            "metadata": {},
        }
        self.db.add_page(newer_id, newer_pdf.name, record, detect_entities(content))
        self.db.finish_document(newer_id, 1)
        self.db.recompute_current_versions()

        current = self.search.search("phase fail")
        all_revisions = self.search.search("phase fail", version_scope="all")
        self.assertEqual([item["revision_label"] for item in current], ["Rev B"])
        self.assertEqual({item["revision_label"] for item in all_revisions}, {"Rev A", "Rev B"})

    def test_removing_document_removes_search_evidence(self):
        self.db.remove_document(self.document_id)
        self.assertEqual(self.search.search("phase fail"), [])
        self.assertEqual(self.search.find_entity("LIT0101"), [])


if __name__ == "__main__":
    unittest.main()
