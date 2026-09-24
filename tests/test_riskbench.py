from dataclasses import replace

import pytest

from riskbench.cases import Case, Evidence, generate_cases
from riskbench.cli import main
from riskbench.engine import POLICY_V1, POLICY_V2, decide, ground_truth
from riskbench.evaluate import compare, impact
from riskbench.extract import extract, extract_keywords, extract_keywords_negex


def case(*docs: tuple[str, str], issued: str = "2026-06-01") -> Case:
    evidence = tuple(Evidence(f"x-{kind}", kind, issued, text) for kind, text in docs)
    return Case("x", evidence, {})


CLEAN = (
    ("ledger", "No invoices are past due in the last 12 months."),
    ("registry", "No change of ownership has been recorded."),
    ("audit", "The auditor issued an unqualified opinion."),
    ("screening", "No match against consolidated sanctions lists."),
)


def facts(c: Case, extractor=extract) -> dict:
    return {f.name: f.value for f in extractor(c)[0]}


def test_negations_and_unqualified_are_read_correctly():
    values = facts(case(*CLEAN))
    assert values == {
        "max_days_past_due": 0,
        "days_since_ownership_change": None,
        "audit_opinion": "clean",
        "screening_similarity": 0.0,
    }
    naive = facts(case(*CLEAN), extract_keywords)
    assert naive["max_days_past_due"] == 45 and naive["audit_opinion"] == "qualified"
    assert naive["screening_similarity"] == 0.95  # "no match" contains "match"
    assert facts(case(*CLEAN), extract_keywords_negex)["screening_similarity"] == 0.0


@pytest.mark.parametrize(
    "text, days",
    [
        ("3 invoices are past due, the oldest by 97 days.", 97),
        ("Oldest past-due invoice: 45 days.", 45),
        ("Payment on invoice INV-123 is 12 days past due.", 12),
    ],
)
def test_past_due_numbers(text, days):
    assert facts(case(("ledger", text)))["max_days_past_due"] == days


def test_dates_in_two_formats():
    for text in ("Ownership changed on 2026-05-01.", "Controlling shareholder replaced on 01 May 2026."):
        assert facts(case(("registry", text)))["days_since_ownership_change"] == 60


def test_clean_case_clears_with_no_findings():
    decision = decide(case(*CLEAN))
    assert decision.decision == "clear" and decision.findings == [] and decision.score == 0


def test_hard_stop_escalates_even_with_missing_documents():
    decision = decide(case(("screening", "Potential match: similarity 0.93 to a listed entity.")))
    assert decision.decision == "escalate"
    assert decision.findings[0]["rule"] == "screening_hard_stop"


def test_missing_or_stale_evidence_abstains():
    missing_audit = case(*[d for d in CLEAN if d[0] != "audit"])
    assert decide(missing_audit).decision == "needs_evidence"
    assert decide(missing_audit).missing == ["audit"]
    stale = case(*CLEAN, issued="2025-01-01")  # screening older than 90 days, audit older than 400
    assert set(decide(stale).missing) == {"audit", "screening"}
    assert decide(missing_audit, abstain=False).decision == "clear"


def test_unreadable_document_is_not_assumed_safe():
    unreadable = case(*[d for d in CLEAN if d[0] != "ledger"], ("ledger", "Arrears of 120 days on the account."))
    assert decide(unreadable).decision == "needs_evidence"
    assert decide(unreadable).missing == ["ledger"]


def test_citations_point_at_the_evidence():
    c = case(*CLEAN[1:], ("ledger", "Oldest past-due invoice: 120 days."), ("audit", "Adverse audit opinion issued."))
    decision = decide(c)
    texts = {d.doc_id: d.text for d in c.evidence}
    assert decision.decision == "escalate"
    for finding in decision.findings:
        start, end = finding["span"]
        assert texts[finding["doc_id"]][start:end] == finding["quote"]


def test_policy_versions_are_content_addressed_and_diffable():
    assert POLICY_V1.digest != POLICY_V2.digest
    assert replace(POLICY_V1, version="copy").digest != POLICY_V1.digest  # the version label is content too
    assert set(POLICY_V1.diff(POLICY_V2)) == {"past_due_bands", "ownership_window_days", "screening_review_from"}


def test_generator_is_deterministic_and_ground_truth_is_consistent():
    a, b = generate_cases(50, seed=3), generate_cases(50, seed=3)
    assert [c.evidence for c in a] == [c.evidence for c in b]
    for c in a:
        truth = ground_truth(c)
        if truth != "needs_evidence":
            assert decide(c).decision == truth  # dev phrasing is fully readable


def test_structured_with_abstention_never_clears_a_risky_case():
    for heldout in (False, True):
        report = compare(generate_cases(300, seed=5, heldout=heldout))
        assert report["structured extraction + abstention"]["missed_escalations"] == 0.0
    assert report["keyword baseline"]["missed_escalations"] == 1.0  # held-out phrasing: silently cleared


def test_impact_analysis_counts_moves():
    report = impact(generate_cases(200, seed=0))
    assert report["decisions_changed"] == sum(report["transitions"].values())
    assert all(k.split("->")[0] != k.split("->")[1] for k in report["transitions"])


def test_cli(tmp_path, capsys):
    assert main(["evaluate", "--cases", "50", "--out", str(tmp_path / "e.json")]) == 0
    assert main(["impact", "--cases", "50"]) == 0
    assert main(["review", "c0001", "--cases", "5"]) == 0
    assert "policy" in capsys.readouterr().out
