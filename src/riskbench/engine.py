"""Versioned review policy and the decision engine that applies it with citations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import date

from .cases import REVIEW_DATE, Case
from .extract import Fact, extract

DECISIONS = ("clear", "review", "escalate", "needs_evidence")


@dataclass(frozen=True)
class Policy:
    version: str
    past_due_bands: tuple[tuple[int, int], ...] = ((91, 40), (31, 20), (1, 5))  # (min days, points), strictest first
    ownership_window_days: int = 180
    ownership_points: int = 25
    audit_points: tuple[tuple[str, int], ...] = (("qualified", 30), ("adverse", 60), ("disclaimer", 60))
    audit_max_age_days: int = 400
    screening_hard_stop: float = 0.90
    screening_review_from: float = 0.80
    screening_points: int = 30
    screening_max_age_days: int = 90
    media_points: int = 20
    review_at: int = 25
    escalate_at: int = 60
    required: tuple[str, ...] = ("ledger", "registry", "audit", "screening")

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]

    def diff(self, other: Policy) -> dict[str, tuple]:
        mine, theirs = asdict(self), asdict(other)
        return {k: (mine[k], theirs[k]) for k in mine if k != "version" and mine[k] != theirs[k]}


POLICY_V1 = Policy("2026.1")
POLICY_V2 = replace(
    POLICY_V1,
    version="2026.2",
    past_due_bands=((61, 40), (31, 25), (1, 5)),
    ownership_window_days=365,
    screening_review_from=0.75,
)


@dataclass
class Decision:
    case_id: str
    decision: str
    score: int
    findings: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    policy: str = ""
    trace: list[str] = field(default_factory=list)


def _stale_kinds(case: Case, policy: Policy) -> set[str]:
    limits = {"audit": policy.audit_max_age_days, "screening": policy.screening_max_age_days}
    return {
        d.kind
        for d in case.evidence
        if d.kind in limits and (REVIEW_DATE - date.fromisoformat(d.issued)).days > limits[d.kind]
    }


def _rules(values: dict[str, Fact], policy: Policy) -> tuple[list[tuple[str, int, Fact]], bool]:
    hits, hard_stop = [], False
    if (f := values.get("max_days_past_due")) and f.value:
        for min_days, points in policy.past_due_bands:
            if f.value >= min_days:
                hits.append((f"past_due>={min_days}d", points, f))
                break
    f = values.get("days_since_ownership_change")
    if f and f.value is not None and f.value <= policy.ownership_window_days:
        hits.append((f"ownership_change<={policy.ownership_window_days}d", policy.ownership_points, f))
    if (f := values.get("audit_opinion")) and f.value in dict(policy.audit_points):
        hits.append((f"audit_{f.value}", dict(policy.audit_points)[f.value], f))
    if (f := values.get("screening_similarity")) and f.value:
        if f.value >= policy.screening_hard_stop:
            hits.append(("screening_hard_stop", 0, f))
            hard_stop = True
        elif f.value >= policy.screening_review_from:
            hits.append(("screening_near_match", policy.screening_points, f))
    if (f := values.get("adverse_media")) and f.value:
        hits.append(("adverse_media", policy.media_points, f))
    return hits, hard_stop


def decide(case: Case, policy: Policy = POLICY_V1, extractor=extract, abstain: bool = True) -> Decision:
    """Apply ``policy`` to the facts ``extractor`` finds.

    Order matters: evidence that already justifies escalation is acted on even
    if other documents are missing; otherwise, a missing, stale or unreadable
    required document produces ``needs_evidence`` instead of a guess.
    """
    facts, unreadable = extractor(case)
    stale = _stale_kinds(case, policy)
    kinds = {d.doc_id: d.kind for d in case.evidence}
    usable = {f.name: f for f in facts if kinds[f.doc_id] not in stale}
    present = {d.kind for d in case.evidence}
    missing = sorted(k for k in policy.required if k not in present or k in stale or k in unreadable)
    hits, hard_stop = _rules(usable, policy)
    score = sum(points for _, points, _ in hits)
    trace = [f"policy {policy.version} ({policy.digest})", f"facts: {sorted(usable)}"]
    if stale:
        trace.append(f"stale: {sorted(stale)}")
    if hard_stop or score >= policy.escalate_at:
        decision = "escalate"
    elif missing and abstain:
        decision = "needs_evidence"
    elif score >= policy.review_at:
        decision = "review"
    else:
        decision = "clear"
    trace.append(f"score {score} → {decision}")
    findings = [
        {"rule": rule, "points": points, "doc_id": f.doc_id, "span": [f.start, f.end], "quote": f.quote}
        for rule, points, f in hits
    ]
    return Decision(
        case.case_id, decision, score, findings, missing if decision == "needs_evidence" else [], policy.digest, trace
    )


def ground_truth(case: Case, policy: Policy = POLICY_V1) -> str:
    """The decision the policy prescribes given what the documents really say."""

    def perfect(c: Case):
        facts = []
        for name, value in c.facts.items():
            if name == "present":
                continue
            kind = {
                "max_days_past_due": "ledger",
                "days_since_ownership_change": "registry",
                "audit_opinion": "audit",
                "screening_similarity": "screening",
                "adverse_media": "media",
            }[name]
            doc = next((d for d in c.evidence if d.kind == kind), None)
            if doc is not None:
                facts.append(Fact(name, value, doc.doc_id, 0, 0, ""))
        return facts, []

    return decide(case, policy, extractor=perfect).decision
