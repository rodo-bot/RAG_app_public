from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

from .paths import APP_ROOT


KNOWN_TESSERACT_PATHS = (
    APP_ROOT / "tools" / "tesseract" / "tesseract.exe",
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


@lru_cache(maxsize=1)
def find_tesseract() -> Path | None:
    executable = shutil.which("tesseract")
    if executable:
        return Path(executable)
    return next((path for path in KNOWN_TESSERACT_PATHS if path.exists()), None)


def ocr_image(image_path: Path, timeout_seconds: int = 180) -> tuple[str, float]:
    executable = find_tesseract()
    if not executable:
        return "", 0.0
    process = subprocess.run(
        [str(executable), str(image_path), "stdout", "-l", "eng", "--psm", "11"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode != 0:
        return "", 0.0
    text = process.stdout.strip()
    confidence = 0.72 if len(text) >= 100 else (0.55 if text else 0.0)
    return text, confidence


def ocr_bitmap(image: Image.Image, timeout_seconds: int = 180) -> tuple[str, float]:
    """Run Tesseract from memory, avoiding a temporary PNG for every page."""
    executable = find_tesseract()
    if not executable:
        return "", 0.0
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    process = subprocess.run(
        [str(executable), "stdin", "stdout", "-l", "eng", "--psm", "11"],
        input=buffer.getvalue(), capture_output=True,
        timeout=timeout_seconds, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode != 0:
        return "", 0.0
    text = process.stdout.decode("utf-8", errors="replace").strip()
    confidence = 0.72 if len(text) >= 100 else (0.55 if text else 0.0)
    return text, confidence
