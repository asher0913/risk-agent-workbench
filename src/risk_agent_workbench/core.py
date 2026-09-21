from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json


@dataclass(frozen=True)
class Evidence:
    source_id: str
    text: str


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    keywords: tuple[str, ...]
    weight: int
    required_sources: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Case:
    case_id: str
    evidence: tuple[Evidence, ...]


class VersionedPolicyStore:
    def __init__(self) -> None:
        self._versions: dict[str, tuple[PolicyRule, ...]] = {}

    def publish(self, version: str, rules: list[PolicyRule]) -> None:
        if version in self._versions:
            raise ValueError("policy versions are immutable")
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule id")
        self._versions[version] = tuple(rules)

    def snapshot(self, version: str) -> tuple[PolicyRule, ...]:
        return self._versions[version]


class RiskAnalyst:
    def __init__(self, store: VersionedPolicyStore, version: str) -> None:
        self.rules = store.snapshot(version)
        self.version = version

    def analyze(self, case: Case) -> dict[str, object]:
        source_map = {item.source_id: item for item in case.evidence}
        corpus = " ".join(item.text.lower() for item in case.evidence)
        findings = []
        missing = set()
        trace = ["normalize_evidence", f"load_policy:{self.version}"]
        for rule in self.rules:
            matched = [keyword for keyword in rule.keywords if keyword.lower() in corpus]
            if not matched:
                continue
            absent = set(rule.required_sources) - set(source_map)
            if absent:
                missing.update(absent)
                trace.append(f"defer:{rule.rule_id}")
                continue
            citations = [source_id for source_id, item in source_map.items() if any(k.lower() in item.text.lower() for k in matched)]
            findings.append({
                "rule_id": rule.rule_id,
                "weight": rule.weight,
                "matched": matched,
                "citations": citations,
                "rationale": rule.rationale,
            })
            trace.append(f"apply:{rule.rule_id}")
        score = min(100, sum(int(item["weight"]) for item in findings))
        if missing:
            decision = "needs_evidence"
        elif score >= 60:
            decision = "escalate"
        elif score >= 25:
            decision = "review"
        else:
            decision = "clear"
        trace.append(f"decision:{decision}")
        return {
            "case_id": case.case_id,
            "policy_version": self.version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "score": score,
            "decision": decision,
            "missing_sources": sorted(missing),
            "findings": findings,
            "trace": trace,
        }


def fixture() -> tuple[RiskAnalyst, list[tuple[Case, str]]]:
    store = VersionedPolicyStore()
    store.publish("2026.1", [
        PolicyRule("late-payment", ("late payment", "past due"), 35, ("ledger",), "Repeated delinquency requires manual review."),
        PolicyRule("ownership-change", ("ownership changed",), 30, ("registry",), "Recent ownership changes increase verification needs."),
        PolicyRule("auditor-note", ("qualified opinion",), 45, ("audit",), "A qualified audit opinion requires escalation."),
    ])
    analyst = RiskAnalyst(store, "2026.1")
    cases = [
        (Case("stable", (Evidence("ledger", "All invoices paid on time."),)), "clear"),
        (Case("delinquent", (Evidence("ledger", "Two invoices were past due and one was a late payment."),)), "review"),
        (Case("compound", (Evidence("ledger", "Past due balance."), Evidence("audit", "Qualified opinion issued."))), "escalate"),
        (Case("missing", (Evidence("note", "Ownership changed last month."),)), "needs_evidence"),
    ]
    return analyst, cases


def demo() -> dict[str, object]:
    analyst, cases = fixture()
    reports = [analyst.analyze(case) for case, _ in cases]
    accuracy = sum(report["decision"] == expected for report, (_, expected) in zip(reports, cases)) / len(cases)
    cited = [finding for report in reports for finding in report["findings"]]
    return {
        "cases": len(cases),
        "decision_accuracy": accuracy,
        "all_findings_cited": all(bool(item["citations"]) for item in cited),
        "decisions": {report["case_id"]: report["decision"] for report in reports},
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, sort_keys=True))
