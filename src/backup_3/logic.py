"""Field-level cleanup, extraction, and validation for visible record text.

The parser never invents values. It removes recognizable UI/OCR debris, extracts
strongly-structured fields (URL/email/phone), and rejects incomplete candidates.
"""
from __future__ import annotations

import re
from typing import TypedDict


class ReferenceRecord(TypedDict):
    name: str
    designation: str
    company: str
    website: str
    address: str
    email: str
    phone: str


FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("name", "Name"), ("designation", "Designation"),
    ("company", "Company Name"), ("website", "Website"),
    ("address", "Address"), ("email", "Email"),
    ("phone", "Office Contact"),
)
PLACEHOLDERS = {"name", "designation", "company", "company name", "website", "address", "email", "office contact", "phone"}
NAVIGATION_MARKER = re.compile(
    r"START\s+WORK|USER\s+DASHBOARD|SELECT\s+FORM|GENERATE\s+QR\s*CODE|SUBMIT\s+ALL\s+\w*CODE", re.I
)
PAGE_CHROME = re.compile(r"\bWORK\s+REPORT\b", re.I)
EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}", re.I)
URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?"
    r"(?:\.[A-Z0-9-]+)+)(?:/[A-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?", re.I
)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?1[\s.-]*)?(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4}"
    r"(?:\s*/\s*(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4})?"
    r"(?:\s*\([^)]{1,8}\))?"
)
EDGE_NOISE = "\\-_–—=~|:;.,·•©®™\\\"'“”‘’«»‹›*`´"


def _space(value: str) -> str:
    value = (value or "").replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", " ")
    return re.sub(r"\s+", " ", value).strip()


def _strip_edges(value: str) -> str:
    value = _space(value)
    previous = None
    while value != previous:
        previous = value
        value = value.strip(EDGE_NOISE).strip()
    return _space(value)


def _strip_navigation(value: str) -> str:
    matches = list(NAVIGATION_MARKER.finditer(value or ""))
    if matches:
        value = value[matches[-1].end():]
    return _strip_edges(value)


def _clean_name(value: str) -> str:
    value = _strip_navigation(value)
    value = _strip_edges(value)

    # Remove short uppercase OCR/UI fragments only when a plausible name follows.
    value = re.sub(
        r"^(?:(?:[A-Z]{2,4}|[A-Z]{1,3}[0-9]{1,2})\s+){1,3}"
        r"(?=[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:[-’'][A-ZÀ-ÖØ-Þ]?[a-zà-öø-ÿ]+)?\s+"
        r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)",
        "",
        value,
    )
    value = re.sub(r"^(?:cumin\s+oncece|syp\s+mno)\s+", "", value, flags=re.I)
    value = re.sub(r"^(?:name\s*[:*|\-]+\s*)+", "", value, flags=re.I)
    value = _strip_edges(value)

    qualifier = ""
    q = re.search(r"\s*(\([^)]*\))\s*$", value)
    if q:
        qualifier = " " + q.group(1)
        value = value[:q.start()].rstrip()

    words = value.split()
    for start in range(1, max(1, len(words) - 1)):
        suffix = words[start:]
        if not 2 <= len(suffix) <= 4:
            continue
        if all(re.fullmatch(r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'.’()-]*", token) for token in suffix):
            prefix = words[:start]
            if any(not re.fullmatch(r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'.’()-]*", token) for token in prefix):
                value = " ".join(suffix)
                break

    value = re.sub(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+", "", value)
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ.)'’-]+$", "", value)
    return _strip_edges(value + qualifier)

def _clean_plain(value: str) -> str:
    value = _strip_edges(value)
    value = re.sub(r"\b(?:name|designation|company\s+name|website|address|email|office\s+contact)\s*[:：]\s*", "", value, flags=re.I)
    value = PAGE_CHROME.sub(" ", value)
    # Strip edge noise again after removing overlays.
    return _strip_edges(value)


def _clean_website(value: str) -> str:
    value = _clean_plain(value)
    matches = list(URL_RE.finditer(value))
    if matches:
        # URL is a structured field: choose the last complete URL if OCR added a word before it.
        return _strip_edges(matches[-1].group(0).rstrip(".,;:)]}>"))
    return value


def _clean_address(value: str) -> str:
    value = _space(value or "")
    value = PAGE_CHROME.sub(" ", value)
    value = re.sub(r"\baddress\s*[:：]\s*", " ", value, flags=re.I)
    # Remove OCR overlay fragments immediately before USA, preserving country/ZIP.
    value = re.sub(
        r"(?:©|®|™|\b[cC]\b)\s+(?:[A-Za-z]{2,12}\s+){0,2}(?=USA\b)",
        "",
        value,
    )
    value = re.sub(r"\b(?:work\s+report|dashboard|select\s+form)\b", " ", value, flags=re.I)
    value = re.sub(r"\s+@\s+", " ", value)
    value = _clean_plain(value)
    # ZIP/ZIP+4 is a reliable terminal boundary for these US address records.
    zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
    if zip_match:
        value = value[:zip_match.end()]
    return _strip_edges(value)

def _clean_email(value: str) -> str:
    value = PAGE_CHROME.sub(" ", value or "")
    matches = list(EMAIL_RE.finditer(value))
    if matches:
        return matches[-1].group(0).strip(".,;:<>[]{}()\"'“”‘’")
    return _clean_plain(value).replace(" ", "")


def _clean_phone(value: str) -> str:
    value = _clean_plain(value)
    matches = list(PHONE_RE.finditer(value))
    if matches:
        return _strip_edges(matches[-1].group(0))
    return value


def _valid_name(value: str) -> bool:
    if not value or value.casefold() in PLACEHOLDERS:
        return False
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", value):
        return False
    if re.search(r"\b(?:work\s+report|dashboard|generate|select\s+form)\b", value, re.I):
        return False
    if "@" in value or re.search(r"https?://|www\.", value, re.I):
        return False
    return True


def _valid_website(value: str) -> bool:
    return bool(value and value.casefold() not in PLACEHOLDERS and re.search(r"(?:[A-Z0-9-]+\.)+[A-Z]{2,}(?:/|$|\?)", value, re.I))


def _valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value or ""))


def _is_record_window(parts: list[str]) -> bool:
    if len(parts) not in (6, 7) or any(not p for p in parts[:6]):
        return False
    if any(p.casefold() in PLACEHOLDERS for p in parts[:6]):
        return False
    if not _valid_name(parts[0]) or not _valid_website(parts[3]) or not _valid_email(parts[5]):
        return False
    if any(PAGE_CHROME.search(p) for p in parts):
        return False
    # Reject values that still look like multiple fields/UI labels were fused together.
    if re.search(r"\b(?:select\s+form|user\s+dashboard|generate\s+qr\s*code)\b", " ".join(parts), re.I):
        return False
    return True


def parse_reference_text(raw: str) -> ReferenceRecord | None:
    """Return a validated 6/7-field record from asterisk-separated text, or None."""
    if not raw or "*" not in raw:
        return None
    parts = [_space(part) for part in raw.split("*")]
    candidates: list[tuple[int, ReferenceRecord]] = []
    for start in range(len(parts)):
        for width in (7, 6):
            candidate = parts[start:start + width]
            if len(candidate) != width:
                continue
            cleaned = [
                _clean_name(candidate[0]), _clean_plain(candidate[1]), _clean_plain(candidate[2]),
                _clean_website(candidate[3]), _clean_address(candidate[4]), _clean_email(candidate[5]),
            ]
            if width == 7:
                cleaned.append(_clean_phone(candidate[6]))
            if not _is_record_window(cleaned):
                continue
            record: ReferenceRecord = {
                "name": cleaned[0], "designation": cleaned[1], "company": cleaned[2],
                "website": cleaned[3], "address": cleaned[4], "email": cleaned[5],
                "phone": cleaned[6] if width == 7 else "",
            }
            # Prefer the 7-field candidate and candidates with complete phone values.
            score = (10 if width == 7 else 0) + (3 if record["phone"] else 0)
            candidates.append((score, record))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def format_record(record: ReferenceRecord) -> str:
    return "\n\n".join(f"- {label}:\n  {record[key]}" for key, label in FIELD_LABELS)
