"""Decision quality, abstention, citation validity and policy-change impact."""

from __future__ import annotations

from collections import Counter

from .cases import Case
from .engine import DECISIONS, POLICY_V1, POLICY_V2, Policy, decide, ground_truth
from .extract import extract, extract_keywords, extract_keywords_negex

SYSTEMS = {
    "keyword baseline": {"extractor": extract_keywords, "abstain": False},
    "keyword + negation baseline": {"extractor": extract_keywords_negex, "abstain": False},
    "structured extraction, no abstention": {"extractor": extract, "abstain": False},
    "structured extraction + abstention": {"extractor": extract, "abstain": True},
}


def evaluate(cases: list[Case], system: dict, policy: Policy = POLICY_V1) -> dict:
    truth = [ground_truth(c, policy) for c in cases]
    predicted = [decide(c, policy, **system) for c in cases]
    pairs = list(zip(truth, (p.decision for p in predicted), strict=True))
    confusion = Counter(pairs)
    n = len(cases)
    risky = sum(t == "escalate" for t in truth)
    clean = sum(t == "clear" for t in truth)
    needs = sum(t == "needs_evidence" for t in truth)
    abstained = sum(p == "needs_evidence" for _, p in pairs)
    citations = [f for p in predicted for f in p.findings]
    by_id = {d.doc_id: d for c in cases for d in c.evidence}
    valid_citations = sum(by_id[f["doc_id"]].text[f["span"][0] : f["span"][1]] == f["quote"] != "" for f in citations)
    return {
        "accuracy": sum(t == p for t, p in pairs) / n,
        "missed_escalations": sum(t == "escalate" and p == "clear" for t, p in pairs) / risky if risky else 0.0,
        "escalations_not_escalated": sum(t == "escalate" and p != "escalate" for t, p in pairs) / risky
        if risky
        else 0.0,
        "false_escalations_of_clean": sum(t == "clear" and p == "escalate" for t, p in pairs) / clean if clean else 0.0,
        "clean_not_cleared": sum(t == "clear" and p != "clear" for t, p in pairs) / clean if clean else 0.0,
        "abstention_rate": abstained / n,
        "abstention_recall": sum(t == p == "needs_evidence" for t, p in pairs) / needs if needs else 0.0,
        "guessed_despite_missing_evidence": sum(t == "needs_evidence" and p in ("clear", "review") for t, p in pairs)
        / needs
        if needs
        else 0.0,
        "citations": len(citations),
        "citation_validity": valid_citations / len(citations) if citations else 1.0,
        "confusion": {f"{t}->{p}": c for (t, p), c in sorted(confusion.items())},
        "truth_distribution": dict(Counter(truth)),
    }


def compare(cases: list[Case]) -> dict:
    return {name: evaluate(cases, system) for name, system in SYSTEMS.items()}


def impact(cases: list[Case], old: Policy = POLICY_V1, new: Policy = POLICY_V2, examples: int = 3) -> dict:
    """Shadow-run a policy change: which decisions would move, and why."""
    moves = Counter()
    samples: dict[str, list] = {}
    for case in cases:
        before, after = decide(case, old), decide(case, new)
        if before.decision != after.decision:
            key = f"{before.decision}->{after.decision}"
            moves[key] += 1
            if len(samples.setdefault(key, [])) < examples:
                samples[key].append(
                    {
                        "case_id": case.case_id,
                        "before": [f["rule"] for f in before.findings],
                        "after": [f["rule"] for f in after.findings],
                        "scores": [before.score, after.score],
                    }
                )
    changed = sum(moves.values())
    return {
        "old": old.version,
        "new": new.version,
        "parameter_changes": {
            k: [list(v) if isinstance(v, tuple) else v for v in pair] for k, pair in old.diff(new).items()
        },
        "cases": len(cases),
        "decisions_changed": changed,
        "share_changed": changed / len(cases),
        "transitions": dict(moves.most_common()),
        "examples": samples,
        "decision_counts": {
            old.version: dict(Counter(decide(c, old).decision for c in cases)),
            new.version: dict(Counter(decide(c, new).decision for c in cases)),
        },
    }


__all__ = ["DECISIONS", "SYSTEMS", "compare", "evaluate", "impact"]
