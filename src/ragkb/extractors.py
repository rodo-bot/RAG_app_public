from __future__ import annotations

import csv
import textwrap
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence

from .ocr import find_tesseract, ocr_bitmap
from .text import clean_text


PDF_EXTENSIONS = {".pdf"}
WORD_EXTENSIONS = {".docx"}
SPREADSHEET_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm", ".csv", ".tsv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | WORD_EXTENSIONS | SPREADSHEET_EXTENSIONS | IMAGE_EXTENSIONS


@dataclass
class ExtractedUnit:
    source_label: str
    page_type: str
    text_source: str
    embedded_text: str
    ocr_text: str = ""
    confidence: float = 0.96
    image_count: int = 0
    preview: Image.Image | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def file_type_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in WORD_EXTENSIONS:
        return "word"
    if suffix in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_preview(title: str, subtitle: str, lines: Iterable[str]) -> Image.Image:
    image = Image.new("RGB", (1600, 1050), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1600, 112), fill="#142944")
    draw.text((45, 24), title[:100], fill="white", font=_font(30, bold=True))
    draw.text((47, 70), subtitle[:150], fill="#b9d8f5", font=_font(18))
    y = 145
    body_font = _font(20)
    for source_line in lines:
        wrapped = textwrap.wrap(str(source_line), width=118, replace_whitespace=False) or [""]
        for line in wrapped:
            if y > 1010:
                draw.text((1325, 1005), "Preview truncated", fill="#7a8798", font=_font(16))
                return image
            draw.text((48, y), line, fill="#223750", font=body_font)
            y += 27
        y += 5
    return image


def _chunk_lines(lines: list[tuple[int, str]], max_characters: int = 6500, max_rows: int = 90) -> list[list[tuple[int, str]]]:
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    characters = 0
    for row_number, line in lines:
        if current and (characters + len(line) > max_characters or len(current) >= max_rows):
            chunks.append(current)
            current = []
            characters = 0
        current.append((row_number, line))
        characters += len(line)
    if current:
        chunks.append(current)
    return chunks


def _cell_text(formula: Any, cached: Any) -> str:
    if formula is None and cached is None:
        return ""
    formula_value = getattr(formula, "text", formula)
    formula_text = str(formula_value) if formula_value is not None else ""
    cached_text = str(cached) if cached is not None else ""
    if formula_text.startswith("="):
        return f"{cached_text} [formula: {formula_text}]" if cached_text and cached_text != formula_text else formula_text
    return formula_text or cached_text


def extract_workbook(path: Path) -> list[ExtractedUnit]:
    if path.suffix.lower() in {".csv", ".tsv"}:
        return _extract_delimited(path)

    from openpyxl import load_workbook

    formula_book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    value_book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    units: list[ExtractedUnit] = []
    try:
        for formula_sheet in formula_book.worksheets:
            value_sheet = value_book[formula_sheet.title]
            rows: list[tuple[int, str]] = []
            for row_number, (formula_row, value_row) in enumerate(
                zip_longest(formula_sheet.iter_rows(), value_sheet.iter_rows(), fillvalue=()), start=1
            ):
                cells: list[str] = []
                for formula_cell, value_cell in zip_longest(formula_row, value_row, fillvalue=None):
                    if formula_cell is None:
                        continue
                    value = _cell_text(formula_cell.value, getattr(value_cell, "value", None))
                    if value:
                        cells.append(f"{formula_cell.coordinate}: {value}")
                if cells:
                    rows.append((row_number, " | ".join(cells)))
            if not rows:
                rows = [(1, "(empty worksheet)")]
            for part, chunk in enumerate(_chunk_lines(rows), start=1):
                first_row, last_row = chunk[0][0], chunk[-1][0]
                source_label = f"Sheet: {formula_sheet.title}, rows {first_row}-{last_row}"
                if len(_chunk_lines(rows)) > 1:
                    source_label += f", part {part}"
                body_lines = [line for _, line in chunk]
                text = clean_text(
                    "\n".join(
                        [f"Workbook: {path.name}", f"Worksheet: {formula_sheet.title}", f"Rows: {first_row}-{last_row}"]
                        + body_lines
                    )
                )
                units.append(
                    ExtractedUnit(
                        source_label=source_label,
                        page_type="spreadsheet_sheet",
                        text_source="spreadsheet_cells",
                        embedded_text=text,
                        preview=_text_preview(path.name, source_label, body_lines),
                        metadata={
                            "sheet_name": formula_sheet.title,
                            "row_start": first_row,
                            "row_end": last_row,
                            "sheet_state": formula_sheet.sheet_state,
                        },
                    )
                )
    finally:
        formula_book.close()
        value_book.close()
    return units


def _extract_delimited(path: Path) -> list[ExtractedUnit]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        for row_number, row in enumerate(csv.reader(stream, delimiter=delimiter), start=1):
            cells = [f"Column {index}: {value}" for index, value in enumerate(row, start=1) if value.strip()]
            if cells:
                rows.append((row_number, " | ".join(cells)))
    if not rows:
        rows = [(1, "(empty file)")]
    units: list[ExtractedUnit] = []
    for part, chunk in enumerate(_chunk_lines(rows), start=1):
        first_row, last_row = chunk[0][0], chunk[-1][0]
        source_label = f"Rows {first_row}-{last_row}"
        body_lines = [line for _, line in chunk]
        text = clean_text("\n".join([f"Spreadsheet: {path.name}", source_label] + body_lines))
        units.append(
            ExtractedUnit(
                source_label=source_label,
                page_type="spreadsheet_sheet",
                text_source="spreadsheet_cells",
                embedded_text=text,
                preview=_text_preview(path.name, source_label, body_lines),
                metadata={"row_start": first_row, "row_end": last_row, "part": part},
            )
        )
    return units


def _iter_word_blocks(document):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            text = clean_text(paragraph.text)
            if text:
                style = paragraph.style.name if paragraph.style else ""
                yield ("heading" if style.lower().startswith("heading") else "paragraph", text)
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            for row_number, row in enumerate(table.rows, start=1):
                values = [clean_text(cell.text) for cell in row.cells]
                if any(values):
                    yield "table", f"Table row {row_number}: " + " | ".join(values)


def extract_word(path: Path) -> list[ExtractedUnit]:
    from docx import Document

    document = Document(path)
    chunks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    current_title = ""
    characters = 0
    for kind, text in _iter_word_blocks(document):
        if kind == "heading" and current and characters >= 1200:
            chunks.append((current_title, current))
            current = []
            characters = 0
        if kind == "heading":
            current_title = text
            current.append(f"Heading: {text}")
        else:
            current.append(text)
        characters += len(text)
        if characters >= 6500:
            chunks.append((current_title, current))
            current = []
            current_title = ""
            characters = 0
    if current:
        chunks.append((current_title, current))
    if not chunks:
        chunks = [("", ["(no readable paragraphs or tables)"])]

    units: list[ExtractedUnit] = []
    for part, (title, lines) in enumerate(chunks, start=1):
        source_label = f"Section {part}" + (f": {title}" if title else "")
        text = clean_text("\n".join([f"Word document: {path.name}", source_label] + lines))
        units.append(
            ExtractedUnit(
                source_label=source_label,
                page_type="word_section",
                text_source="word_text",
                embedded_text=text,
                image_count=len(document.inline_shapes),
                preview=_text_preview(path.name, source_label, lines),
                metadata={"section_number": part, "heading": title, "embedded_images": len(document.inline_shapes)},
            )
        )
    return units


def extract_image(path: Path, enable_ocr: bool = True) -> list[ExtractedUnit]:
    units: list[ExtractedUnit] = []
    with Image.open(path) as source:
        total_frames = int(getattr(source, "n_frames", 1))
        image_format = source.format or path.suffix.lstrip(".").upper()
        for frame_number, frame in enumerate(ImageSequence.Iterator(source), start=1):
            image = ImageOps.exif_transpose(frame.copy()).convert("RGB")
            original_width, original_height = image.size
            preview = image.copy()
            preview.thumbnail((2600, 2600))
            ocr_text = ""
            confidence = 0.0
            if enable_ocr and find_tesseract() is not None:
                ocr_text, confidence = ocr_bitmap(image)
                ocr_text = clean_text(ocr_text)
            source_label = "Image" if total_frames == 1 else f"Image frame {frame_number} of {total_frames}"
            units.append(
                ExtractedUnit(
                    source_label=source_label,
                    page_type="image",
                    text_source="ocr" if ocr_text else "image_only",
                    embedded_text=clean_text(
                        f"Image file: {path.name}\nDimensions: {original_width} x {original_height} pixels\nFormat: {image_format}"
                    ),
                    ocr_text=ocr_text,
                    confidence=confidence,
                    image_count=1,
                    preview=preview,
                    metadata={
                        "frame_number": frame_number,
                        "frame_count": total_frames,
                        "pixel_width": original_width,
                        "pixel_height": original_height,
                        "image_format": image_format,
                        "ocr_attempted": bool(enable_ocr and find_tesseract() is not None),
                    },
                )
            )
    return units


def extract_non_pdf(path: Path, enable_ocr: bool = True) -> list[ExtractedUnit]:
    file_type = file_type_for(path)
    if file_type == "word":
        return extract_word(path)
    if file_type == "spreadsheet":
        return extract_workbook(path)
    if file_type == "image":
        return extract_image(path, enable_ocr=enable_ocr)
    raise ValueError(f"Unsupported file type: {path.suffix}")
