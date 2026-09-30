"""
S1 entity extraction (PIPELINE_STAGES §3 action 5): dates, contact names, file names — plus
e-mail addresses. Deterministic rules only (S2 is the one and only LLM call).

Entities are ADVISORY hints. They carry no authority: nothing in the pipeline decides risk,
mutation, capability or access from them.

Coverage is deliberately narrow and precise (English): ISO dates (`2026-03-05`), "5 March 2026",
"March 5, 2026", and relative words (today/tomorrow/yesterday) when the authoritative date is
known; names from `named X Y`, `called X Y`, `contact|customer|client X Y` and quoted strings;
file names by known extension; e-mail addresses.
"""
from __future__ import annotations

import datetime as dt
import re
import types

MAX_PER_KIND = 20
MAX_LEN = 100

_MONTHS = types.MappingProxyType({m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)})
_MONTH_RE = "|".join(_MONTHS)
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_D_MON_Y = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})[a-z]*,?\s+(\d{{4}})\b", re.I)
_MON_D_Y = re.compile(rf"\b({_MONTH_RE})[a-z]*\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_RELATIVE = re.compile(r"\b(today|tomorrow|yesterday)\b", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_FILE = re.compile(r"(?<![\w@])[\w\-]+(?:\.[\w\-]+)*\.(?:pdf|docx?|xlsx?|csv|txt|png|jpe?g|zip|pptx?)\b", re.I)
_NAME = r"[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+){0,3}"
_NAMED = re.compile(rf"\b(?:named|called)\s+({_NAME})")
_ROLE = re.compile(rf"\b(?:contact|customer|client)\s+({_NAME})")
_QUOTED = re.compile(r'"([^"\n]{2,60})"')


def _date(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def _add(bucket: list[str], value: str | None) -> None:
    if value and len(value) <= MAX_LEN and value not in bucket and len(bucket) < MAX_PER_KIND:
        bucket.append(value)


def extract_entities(text: str, today: dt.date | None = None) -> dict[str, list[str]]:
    """{"dates": [...ISO...], "emails": [...], "files": [...], "names": [...]}; empty kinds omitted."""
    found: dict[str, list[str]] = {"dates": [], "emails": [], "files": [], "names": []}

    for y, mo, d in _ISO.findall(text):
        _add(found["dates"], _date(int(y), int(mo), int(d)))
    for d, mon, y in _D_MON_Y.findall(text):
        _add(found["dates"], _date(int(y), _MONTHS[mon.lower()], int(d)))
    for mon, d, y in _MON_D_Y.findall(text):
        _add(found["dates"], _date(int(y), _MONTHS[mon.lower()], int(d)))
    if today is not None:
        for word in _RELATIVE.findall(text):
            delta = {"today": 0, "tomorrow": 1, "yesterday": -1}[word.lower()]
            _add(found["dates"], (today + dt.timedelta(days=delta)).isoformat())

    for e in _EMAIL.findall(text):
        _add(found["emails"], e)
    emails = set(found["emails"])
    for f in _FILE.findall(text):
        if f not in emails:
            _add(found["files"], f)

    for pattern in (_NAMED, _ROLE):
        for n in pattern.findall(text):
            _add(found["names"], n)
    for q in _QUOTED.findall(text):
        if q not in emails and not _FILE.fullmatch(q) and not _ISO.fullmatch(q):
            _add(found["names"], q)
    return {k: v for k, v in found.items() if v}
