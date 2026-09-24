"""Seeded counterparty-review cases: evidence documents plus the facts they really state.

Each case has up to five documents (ledger, registry, audit, sanctions
screening, media). The generator writes them in varied natural phrasing,
including the constructions that break keyword matching — negation ("no
invoices are past due"), "unqualified opinion" containing "qualified opinion",
"no match" containing "match" — and it removes or ages documents so that some
cases cannot be decided without more evidence. ``heldout=True`` switches to a
second set of phrasings that were not used while writing the extractors.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

REVIEW_DATE = date(2026, 6, 30)
KINDS = ("ledger", "registry", "audit", "screening", "media")


@dataclass(frozen=True)
class Evidence:
    doc_id: str
    kind: str
    issued: str  # ISO date
    text: str


@dataclass(frozen=True)
class Case:
    case_id: str
    evidence: tuple[Evidence, ...]
    facts: dict = field(hash=False)  # what the documents really say (ground truth for extraction)


def _d(days_ago: int) -> date:
    return REVIEW_DATE - timedelta(days=days_ago)


LEDGER_NONE = (
    "No invoices are past due in the last 12 months.",
    "All invoices were settled on time; nothing is past due.",
    "Past-due balance: none.",
)
LEDGER_SOME = (
    "{n} invoices are past due, the oldest by {d} days.",
    "Oldest past-due invoice: {d} days.",
    "Payment on invoice INV-{k} is {d} days past due.",
)
REGISTRY_NONE = ("No change of ownership has been recorded.", "Ownership unchanged since incorporation in {y}.")
REGISTRY_CHANGED = ("Ownership changed on {date}.", "Controlling shareholder replaced on {date}.")
AUDIT = {
    "clean": ("The auditor issued an unqualified opinion.", "Clean audit opinion for FY{y}."),
    "qualified": ("The auditor issued a qualified opinion, citing inventory valuation.", "Qualified audit opinion."),
    "adverse": ("Adverse audit opinion issued.", "The auditor issued an adverse opinion."),
    "disclaimer": ("The auditor disclaimed an opinion.", "Disclaimer of opinion due to scope limitation."),
}
SCREEN_NONE = ("No match against consolidated sanctions lists.", "Screening complete: no match found.")
SCREEN_HIT = ("Potential match: similarity {s:.2f} to a listed entity.", "Screening hit with similarity {s:.2f}.")
MEDIA_NONE = ("No adverse media found.", "Media search returned no litigation or fraud reports.")
MEDIA_HIT = ("Litigation filed by a former supplier.", "Local press reports a fraud investigation.")

HELDOUT = {
    "ledger_none": ("Nothing outstanding beyond agreed terms.", "Every invoice has been paid within terms."),
    "ledger_some": (
        "Invoice INV-{k} remains unpaid {d} days after its due date.",
        "Arrears of {d} days on the account.",
    ),
    "registry_none": ("Shareholding structure is the same as at the last filing.",),
    "registry_changed": ("The company was acquired by a new parent on {date}.",),
    "audit_clean": ("Opinion: the statements present fairly, in all material respects.",),
    "audit_qualified": ("Except for the matter described, the statements present fairly.",),
    "audit_adverse": ("The financial statements do not present fairly.",),
    "audit_disclaimer": ("The auditor was unable to form an opinion.",),
    "screen_none": ("Name screening returned zero hits.",),
    "screen_hit": ("Name screening: {s:.2f} similarity with a designated party.",),
    "media_none": ("No negative news.",),
    "media_hit": ("A regulator opened an inquiry into the firm.",),
}


def _pick(rng, dev, heldout_key, heldout):
    return rng.choice(HELDOUT[heldout_key] if heldout else dev)


def generate_case(case_id: str, rng: random.Random, heldout: bool = False) -> Case:
    facts: dict = {}
    docs: list[Evidence] = []

    def add(kind: str, text: str, age_days: int) -> None:
        docs.append(Evidence(f"{case_id}-{kind}", kind, _d(age_days).isoformat(), text))

    # ledger
    roll = rng.random()
    days_past_due = 0 if roll < 0.55 else rng.choice([rng.randint(5, 30), rng.randint(31, 90), rng.randint(91, 200)])
    facts["max_days_past_due"] = days_past_due
    if days_past_due == 0:
        text = _pick(rng, LEDGER_NONE, "ledger_none", heldout)
    else:
        text = _pick(rng, LEDGER_SOME, "ledger_some", heldout).format(
            n=rng.randint(1, 4), d=days_past_due, k=rng.randint(100, 999)
        )
    add("ledger", text, rng.randint(1, 30))

    # registry
    changed = rng.random() < 0.25
    facts["days_since_ownership_change"] = rng.randint(10, 700) if changed else None
    if changed:
        when = _d(facts["days_since_ownership_change"]).strftime(rng.choice(["%Y-%m-%d", "%d %B %Y"]))
        text = _pick(rng, REGISTRY_CHANGED, "registry_changed", heldout).format(date=when)
    else:
        text = _pick(rng, REGISTRY_NONE, "registry_none", heldout).format(y=rng.randint(1990, 2015))
    add("registry", text, rng.randint(1, 60))

    # audit
    opinion = rng.choices(["clean", "qualified", "adverse", "disclaimer"], weights=[0.75, 0.15, 0.05, 0.05])[0]
    facts["audit_opinion"] = opinion
    audit_age = rng.randint(420, 700) if rng.random() < 0.1 else rng.randint(30, 300)
    add("audit", _pick(rng, AUDIT[opinion], f"audit_{opinion}", heldout).format(y=_d(audit_age).year), audit_age)

    # screening
    hit = rng.random() < 0.2
    score = round(rng.uniform(0.7, 0.99), 2) if hit else 0.0
    facts["screening_similarity"] = score
    text = (
        _pick(rng, SCREEN_HIT, "screen_hit", heldout).format(s=score)
        if hit
        else _pick(rng, SCREEN_NONE, "screen_none", heldout)
    )
    add("screening", text, rng.randint(120, 300) if rng.random() < 0.1 else rng.randint(1, 60))

    # media (optional evidence)
    adverse = rng.random() < 0.12
    facts["adverse_media"] = adverse
    add(
        "media",
        _pick(rng, MEDIA_HIT if adverse else MEDIA_NONE, "media_hit" if adverse else "media_none", heldout),
        rng.randint(1, 30),
    )

    # Remove some documents: the reviewer must notice what is missing.
    kept = [d for d in docs if not (d.kind != "media" and rng.random() < 0.04)]
    facts["present"] = sorted({d.kind for d in kept})
    return Case(case_id, tuple(kept), facts)


def generate_cases(n: int = 1000, seed: int = 0, heldout: bool = False) -> list[Case]:
    rng = random.Random(seed)
    return [generate_case(f"c{i:04d}", rng, heldout) for i in range(n)]
