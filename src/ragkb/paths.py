from __future__ import annotations

import json
import sys
from pathlib import Path


APP_NAME = "RAG Knowledge Base"


def _application_root() -> Path:
    """Return the portable app folder in source and packaged builds."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # A macOS .app bundle is read-only after installation and signing.
            # Keep the shared desktop/MCP runtime state in the standard writable
            # per-user Application Support directory instead.
            return Path.home() / "Library" / "Application Support" / APP_NAME
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _application_root()
SETTINGS_PATH = APP_ROOT / "settings.json"


def _source_library() -> Path:
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        configured = Path(settings.get("sync_library", "Sync Library"))
        return (configured if configured.is_absolute() else APP_ROOT / configured).resolve()
    return APP_ROOT / "Sync Library"


SYNC_LIBRARY_DIR = _source_library()
DATA_DIR = APP_ROOT / "data"
DATABASE_PATH = DATA_DIR / "knowledge.db"
PREVIEW_DIR = DATA_DIR / "previews"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
MODEL_DIR = APP_ROOT / "models"


def ensure_data_dirs() -> None:
    SYNC_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
