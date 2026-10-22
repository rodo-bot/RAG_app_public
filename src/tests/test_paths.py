import unittest
from pathlib import Path
from unittest.mock import patch

from ragkb.paths import APP_NAME, _application_root


class PathTests(unittest.TestCase):
    def test_frozen_macos_uses_application_support(self):
        home = Path("/Users/tester")
        with (
            patch("ragkb.paths.sys.frozen", True, create=True),
            patch("ragkb.paths.sys.platform", "darwin"),
            patch("ragkb.paths.Path.home", return_value=home),
        ):
            self.assertEqual(
                _application_root(),
                home / "Library" / "Application Support" / APP_NAME,
            )

    def test_other_frozen_platforms_stay_next_to_executable(self):
        executable = Path("C:/Portable/RAG Knowledge Base.exe")
        with (
            patch("ragkb.paths.sys.frozen", True, create=True),
            patch("ragkb.paths.sys.platform", "win32"),
            patch("ragkb.paths.sys.executable", str(executable)),
        ):
            self.assertEqual(_application_root(), executable.resolve().parent)


if __name__ == "__main__":
    unittest.main()
