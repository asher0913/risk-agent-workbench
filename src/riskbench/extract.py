"""Typed fact extraction with character-span citations, and the keyword baseline it replaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .cases import REVIEW_DATE, Case, Evidence


@dataclass(frozen=True)
class Fact:
    name: str
    value: object
    doc_id: str
    start: int
    end: int
    quote: str


def _fact(name: str, value, doc: Evidence, match: re.Match) -> Fact:
    return Fact(name, value, doc.doc_id, match.start(), match.end(), match.group(0))


NEGATED_PAST_DUE = re.compile(r"\b(no invoices are past due|nothing is past due|past-due balance:\s*none)\b", re.I)
DAYS_PAST_DUE = re.compile(r"(?:(\d+)\s+days\s+past\s+due|past[- ]due[^.]*?(\d+)\s+days|oldest by (\d+) days)", re.I)
NO_CHANGE = re.compile(r"\b(no change of ownership|ownership unchanged)\b", re.I)
CHANGE_ON = re.compile(
    r"\b(?:ownership changed|shareholder replaced)\s+on\s+(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Z][a-z]+ \d{4})", re.I
)
OPINIONS = (  # most specific first: "unqualified" must win over "qualified"
    ("clean", re.compile(r"\b(unqualified opinion|clean audit opinion)\b", re.I)),
    ("disclaimer", re.compile(r"\b(disclaimed an opinion|disclaimer of opinion)\b", re.I)),
    ("adverse", re.compile(r"\badverse (audit )?opinion\b", re.I)),
    ("qualified", re.compile(r"\bqualified (audit )?opinion\b", re.I)),
)
NO_MATCH = re.compile(r"\bno match\b", re.I)
SIMILARITY = re.compile(r"similarity\s+(0\.\d+|1\.0+)", re.I)
NO_MEDIA = re.compile(r"\b(no adverse media|no litigation or fraud)\b", re.I)
ADVERSE_MEDIA = re.compile(r"\b(litigation|fraud investigation)\b", re.I)


def _parse_date(text: str) -> date:
    for fmt in ("%Y-%m-%d", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def extract(case: Case) -> tuple[list[Fact], list[str]]:
    """Facts found in the evidence, plus the kinds of document whose content could not be read.

    An unreadable document is treated like a missing one: the engine must not
    assume "no risk" because it failed to parse a sentence.
    """
    facts: list[Fact] = []
    unreadable: list[str] = []
    for doc in case.evidence:
        found = _extract_one(doc)
        if found is None:
            unreadable.append(doc.kind)
        else:
            facts.extend(found)
    return facts, unreadable


def _extract_one(doc: Evidence) -> list[Fact] | None:
    text = doc.text
    if doc.kind == "ledger":
        if m := NEGATED_PAST_DUE.search(text):
            return [_fact("max_days_past_due", 0, doc, m)]
        if m := DAYS_PAST_DUE.search(text):
            days = int(next(g for g in m.groups() if g))
            return [_fact("max_days_past_due", days, doc, m)]
        return None
    if doc.kind == "registry":
        if m := NO_CHANGE.search(text):
            return [_fact("days_since_ownership_change", None, doc, m)]
        if m := CHANGE_ON.search(text):
            return [_fact("days_since_ownership_change", (REVIEW_DATE - _parse_date(m.group(1))).days, doc, m)]
        return None
    if doc.kind == "audit":
        for opinion, pattern in OPINIONS:
            if m := pattern.search(text):
                return [_fact("audit_opinion", opinion, doc, m)]
        return None
    if doc.kind == "screening":
        if m := SIMILARITY.search(text):
            return [_fact("screening_similarity", float(m.group(1)), doc, m)]
        if m := NO_MATCH.search(text):
            return [_fact("screening_similarity", 0.0, doc, m)]
        return None
    if doc.kind == "media":
        if m := NO_MEDIA.search(text):
            return [_fact("adverse_media", False, doc, m)]
        if m := ADVERSE_MEDIA.search(text):
            return [_fact("adverse_media", True, doc, m)]
        return None
    return None


KEYWORDS = {
    "max_days_past_due": ("past due", 45),  # a keyword cannot read the number; assume mid-band
    "days_since_ownership_change": ("ownership changed", 90),
    "audit_opinion": ("qualified opinion", "qualified"),
    "screening_similarity": ("match", 0.95),
    "adverse_media": ("litigation", True),
}
DEFAULTS = {
    "max_days_past_due": 0,
    "days_since_ownership_change": None,
    "audit_opinion": "clean",
    "screening_similarity": 0.0,
    "adverse_media": False,
}
KIND_OF = {
    "max_days_past_due": "ledger",
    "days_since_ownership_change": "registry",
    "audit_opinion": "audit",
    "screening_similarity": "screening",
    "adverse_media": "media",
}


NEGATION_CUES = re.compile(r"\b(no|not|nothing|none|without|never)\b[^.]{0,30}$|\bun$", re.I)


def extract_keywords_negex(case: Case) -> tuple[list[Fact], list[str]]:
    """A stronger baseline: keywords, ignoring occurrences inside a negation window (NegEx-style).

    It still cannot read numbers or dates, so it assumes a mid-band value.
    """
    facts = []
    for name, (keyword, value) in KEYWORDS.items():
        doc = next((d for d in case.evidence if d.kind == KIND_OF[name]), None)
        if doc is None:
            continue
        lowered = doc.text.lower()
        hit = None
        for m in re.finditer(re.escape(keyword), lowered):
            if not NEGATION_CUES.search(lowered[max(0, m.start() - 40) : m.start()]):
                hit = m
                break
        if hit:
            facts.append(Fact(name, value, doc.doc_id, hit.start(), hit.end(), doc.text[hit.start() : hit.end()]))
        else:
            facts.append(Fact(name, DEFAULTS[name], doc.doc_id, 0, 0, ""))
    return facts, []


def extract_keywords(case: Case) -> tuple[list[Fact], list[str]]:
    """The naive baseline: a keyword anywhere in the document triggers the risk factor."""
    facts = []
    for name, (keyword, value) in KEYWORDS.items():
        doc = next((d for d in case.evidence if d.kind == KIND_OF[name]), None)
        if doc is None:
            continue
        index = doc.text.lower().find(keyword)
        if index >= 0:
            facts.append(
                Fact(name, value, doc.doc_id, index, index + len(keyword), doc.text[index : index + len(keyword)])
            )
        else:
            facts.append(Fact(name, DEFAULTS[name], doc.doc_id, 0, 0, ""))
    return facts, []
