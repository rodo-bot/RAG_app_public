from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REVISION_RE = re.compile(r"\b(?:rev(?:ision)?)\s*([a-z]{1,3}|\d{1,4})\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent|pct)\b", re.IGNORECASE)
VERSION_TOKEN_RE = re.compile(
    r"\b(?:rev(?:ision)?\s*(?:[a-z]{1,3}|\d{1,4})|\d{1,3}\s*(?:%|percent|pct)|"
    r"issued\s+for\s+(?:construction|bid)|ifc|ifb|final|draft)\b",
    re.IGNORECASE,
)
SEPARATOR_RE = re.compile(r"[_\-.]+")
NON_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class DocumentVersion:
    relative_path: str
    family_key: str
    revision_label: str
    revision_rank: int
    version_detected: bool


def _letters_rank(value: str) -> int:
    rank = 0
    for character in value.upper():
        rank = rank * 26 + (ord(character) - ord("A") + 1)
    return rank


def _clean_family_part(value: str) -> str:
    value = SEPARATOR_RE.sub(" ", value.lower())
    value = VERSION_TOKEN_RE.sub(" ", value)
    return NON_WORD_RE.sub(" ", value).strip()


def detect_document_version(path: Path, library_root: Path) -> DocumentVersion:
    resolved = path.resolve()
    root = library_root.resolve()
    relative = resolved.relative_to(root)
    relative_text = relative.as_posix()
    searchable = SEPARATOR_RE.sub(" ", str(relative.with_suffix("")))

    label = ""
    rank = 0
    detected = False

    percent_matches = list(PERCENT_RE.finditer(searchable))
    revision_matches = list(REVISION_RE.finditer(searchable))
    lowered = searchable.lower()
    if "issued for construction" in lowered or re.search(r"\bifc\b", lowered):
        label, rank, detected = "IFC", 4000, True
    elif "final" in lowered:
        label, rank, detected = "Final", 3500, True
    elif "issued for bid" in lowered or re.search(r"\bifb\b", lowered):
        label, rank, detected = "IFB", 3000, True
    elif revision_matches:
        value = revision_matches[-1].group(1).upper()
        value_rank = int(value) if value.isdigit() else _letters_rank(value)
        label, rank, detected = f"Rev {value}", 2000 + value_rank, True
    elif percent_matches:
        value = max(0, min(int(percent_matches[-1].group(1)), 100))
        label, rank, detected = f"{value}%", 1000 + value, True
    elif re.search(r"\bdraft\b", lowered):
        label, rank, detected = "Draft", 100, True

    family_parts: list[str] = []
    for index, part in enumerate(relative.with_suffix("").parts):
        cleaned = _clean_family_part(part)
        if cleaned:
            family_parts.append(cleaned)
    family_key = "/".join(family_parts) or _clean_family_part(path.stem) or path.stem.lower()
    return DocumentVersion(relative_text, family_key, label, rank, detected)
