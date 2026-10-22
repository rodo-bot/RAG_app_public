from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SPACE_RE = re.compile(r"\s+")
SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
TAG_RE = re.compile(
    r"\b(?:AI|AIT|AO|DI|DO|FIC|FIT|FQIT|HMI|LIT|LT|MCC|OIT|PI|PLC|PT|SCADA|VFD)"
    r"[\s_-]*\d{2,6}[A-Z]?\b",
    re.IGNORECASE,
)
MODEL_RE = re.compile(
    r"\b(?:"
    r"(?=[A-Z0-9-]{6,}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)+"
    r"|(?=[A-Z0-9]{7,}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{7,}"
    r")\b",
    re.IGNORECASE,
)
DRAWING_RE = re.compile(
    r"\b(?=[A-Z0-9_./&-]*\d)(?:DWG\.?\s*(?:NO\.?\s*)?)?"
    r"[A-Z0-9]{2,}(?:[-_/&][A-Z0-9]{2,}){2,}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DetectedEntity:
    entity_type: str
    display_value: str
    normalized_value: str
    start: int
    end: int


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = SURROGATE_RE.sub(" ", value)
    value = value.replace("\x00", " ").replace("\ufffd", " ")
    return SPACE_RE.sub(" ", value).strip()


def normalize_identifier(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper()
    return re.sub(r"[^A-Z0-9]", "", value)


def search_variants(text: str) -> str:
    """Append compact identifier variants so OCR/search punctuation differences still match."""
    cleaned = clean_text(text)
    variants: set[str] = set()
    for match in TAG_RE.finditer(cleaned):
        variants.add(normalize_identifier(match.group(0)))
    for match in MODEL_RE.finditer(cleaned):
        variants.add(normalize_identifier(match.group(0)))
    return cleaned + (("\n" + " ".join(sorted(variants))) if variants else "")


def detect_entities(text: str) -> list[DetectedEntity]:
    cleaned = clean_text(text)
    found: dict[tuple[str, str], DetectedEntity] = {}
    patterns = (("instrument_tag", TAG_RE), ("model_or_drawing", MODEL_RE), ("drawing_number", DRAWING_RE))
    for entity_type, pattern in patterns:
        for match in pattern.finditer(cleaned):
            display = match.group(0).strip()
            if entity_type != "instrument_tag" and TAG_RE.fullmatch(display):
                continue
            if entity_type == "model_or_drawing" and "-" not in display:
                letter_count = sum(character.isalpha() for character in display)
                digit_count = sum(character.isdigit() for character in display)
                if len(display) > 14 or letter_count < 2 or digit_count < 2:
                    continue
            normalized = normalize_identifier(display)
            if len(normalized) < 4:
                continue
            key = (entity_type, normalized)
            found.setdefault(
                key,
                DetectedEntity(entity_type, display, normalized, match.start(), match.end()),
            )
    return list(found.values())


def query_tokens(query: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", query or "")


def fts_query(query: str) -> str:
    tokens = query_tokens(query)
    if not tokens:
        return ""
    terms = [f'"{token}"' for token in tokens]
    phrase = " AND ".join(terms)
    compact = normalize_identifier(query)
    if len(compact) >= 4 and compact not in {token.upper() for token in tokens}:
        return f'({phrase}) OR "{compact}"'
    return phrase
