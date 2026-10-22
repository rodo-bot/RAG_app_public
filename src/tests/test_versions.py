import tempfile
import unittest
from pathlib import Path

from ragkb.versions import detect_document_version


class VersionTests(unittest.TestCase):
    def test_groups_percent_folders_as_one_family(self):
        root = Path(tempfile.gettempdir()) / "sync-library-version-test"
        eighty = detect_document_version(root / "Project X" / "80 Percent" / "Pump Station.pdf", root)
        ninety = detect_document_version(root / "Project X" / "90 Percent" / "Pump Station.pdf", root)
        self.assertEqual(eighty.family_key, ninety.family_key)
        self.assertLess(eighty.revision_rank, ninety.revision_rank)
        self.assertEqual(ninety.revision_label, "90%")

    def test_groups_revision_filenames_as_one_family(self):
        root = Path(tempfile.gettempdir()) / "sync-library-version-test"
        rev_a = detect_document_version(root / "Electrical" / "MCC Rev A.pdf", root)
        rev_b = detect_document_version(root / "Electrical" / "MCC Revision B.pdf", root)
        self.assertEqual(rev_a.family_key, rev_b.family_key)
        self.assertLess(rev_a.revision_rank, rev_b.revision_rank)

    def test_unversioned_document_remains_unmarked(self):
        root = Path(tempfile.gettempdir()) / "sync-library-version-test"
        item = detect_document_version(root / "Controls" / "Control Narrative.pdf", root)
        self.assertFalse(item.version_detected)
        self.assertEqual(item.revision_label, "")


if __name__ == "__main__":
    unittest.main()
