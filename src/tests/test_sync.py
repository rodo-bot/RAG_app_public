import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ragkb.db import KnowledgeDB
from ragkb.indexer import discover_files, index_library


class SyncTests(unittest.TestCase):
    def test_discovers_nested_files_without_temporary_folder(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "Sync Library"
            nested = root / "Company" / "Product"
            nested.mkdir(parents=True)
            manual = nested / "Manual.PDF"
            manual.write_bytes(b"manual")
            temporary = root / "tmp"
            temporary.mkdir()
            (temporary / "Ignored.pdf").write_bytes(b"temporary")

            self.assertEqual(discover_files(root), [manual.resolve()])

    def test_unchanged_sync_uses_metadata_without_reopening_documents(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "Sync Library"
            root.mkdir()
            source = root / "Stable.pdf"
            source.write_bytes(b"already indexed")
            metadata = source.stat()
            db = KnowledgeDB(Path(temp_name) / "knowledge.db")
            document_id = db.upsert_document(source, "known", metadata.st_size, metadata.st_mtime_ns)
            db.finish_document(document_id, 7)
            events = []

            with patch("ragkb.indexer.index_file") as index_file, patch.object(db, "recompute_current_versions") as refresh:
                report = index_library(root, db=db, progress=events.append)

            index_file.assert_not_called()
            refresh.assert_not_called()
            self.assertEqual((report.skipped, report.pages), (1, 7))
            self.assertEqual(events[0], {"event": "scan", "total_files": 1, "completed_files": 0})
            self.assertEqual(events[-1]["event"], "file_complete")
            self.assertEqual(events[-1]["completed_files"], 1)

    def test_progress_counts_all_library_files_during_changed_file(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "Sync Library"
            root.mkdir()
            stable = root / "A.pdf"
            changed = root / "B.pdf"
            stable.write_bytes(b"stable")
            changed.write_bytes(b"new")
            metadata = stable.stat()
            db = KnowledgeDB(Path(temp_name) / "knowledge.db")
            document_id = db.upsert_document(stable, "known", metadata.st_size, metadata.st_mtime_ns)
            db.finish_document(document_id, 1)
            events = []

            def fake_index_file(path, _db, **kwargs):
                kwargs["progress"]({"event": "page", "document": path.name, "page": 2, "page_count": 4})
                return "indexed", 4

            with patch("ragkb.indexer.index_file", side_effect=fake_index_file) as index_file:
                report = index_library(root, db=db, progress=events.append)

            self.assertEqual(index_file.call_count, 1)
            self.assertEqual((report.skipped, report.indexed), (1, 1))
            page_event = next(event for event in events if event["event"] == "page")
            self.assertEqual((page_event["completed_files"], page_event["total_files"]), (1, 2))
            self.assertEqual(events[-1]["completed_files"], 2)

    def test_relocated_file_is_not_removed_during_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "Sync Library"
            root.mkdir()
            old_path = root / "Old" / "Manual.pdf"
            old_path.parent.mkdir()
            old_path.write_bytes(b"same manual")
            metadata = old_path.stat()
            db = KnowledgeDB(Path(temp_name) / "knowledge.db")
            document_id = db.upsert_document(old_path, "known", metadata.st_size, metadata.st_mtime_ns)
            db.finish_document(document_id, 3)
            new_path = root / "New" / "Manual.pdf"
            new_path.parent.mkdir()
            old_path.rename(new_path)

            def fake_index_file(path, database, **_kwargs):
                current = path.stat()
                database.relocate_document(
                    document_id, path, current.st_size, current.st_mtime_ns,
                    "New/Manual.pdf", "new/manual", "", 0, False,
                )
                return "relocated", 3

            with patch("ragkb.indexer.index_file", side_effect=fake_index_file):
                report = index_library(root, db=db)

            self.assertEqual((report.relocated, report.removed), (1, 0))
            self.assertEqual(db.list_document_records()[0]["path"], str(new_path.resolve()))

    def test_sync_prunes_documents_missing_from_managed_library(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "Sync Library"
            root.mkdir()
            current_pdf = root / "Current.pdf"
            current_pdf.touch()
            missing_pdf = root / "Removed.pdf"
            db = KnowledgeDB(Path(temp_name) / "knowledge.db")
            current_id = db.upsert_document(current_pdf, "keep", 0, 1)
            removed_id = db.upsert_document(missing_pdf, "remove", 0, 1)
            db.finish_document(current_id, 0)
            db.finish_document(removed_id, 0)

            with patch("ragkb.indexer.index_pdf", return_value=("skipped", 0)):
                report = index_library(root, db=db, enable_ocr=False)

            self.assertEqual(report.removed, 1)
            self.assertEqual(report.removed_documents, ["Removed.pdf"])
            self.assertEqual([row["name"] for row in db.list_document_records()], ["Current.pdf"])


if __name__ == "__main__":
    unittest.main()
