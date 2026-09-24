"""``riskbench evaluate | impact | review``."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .cases import generate_cases
from .engine import POLICY_V1, POLICY_V2, decide
from .evaluate import compare, impact

COLUMNS = (
    ("accuracy", "Accuracy"),
    ("missed_escalations", "Risky cases cleared"),
    ("false_escalations_of_clean", "Clean cases escalated"),
    ("guessed_despite_missing_evidence", "Guessed without evidence"),
    ("abstention_rate", "Sent back for evidence"),
)


def _evaluate(args) -> int:
    report = {
        "development": compare(generate_cases(args.cases, seed=0)),
        "held_out_phrasing": compare(generate_cases(args.cases, seed=11, heldout=True)),
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    for suite, systems in report.items():
        print(f"\n{suite} ({args.cases} cases)")
        print("| System | " + " | ".join(label for _, label in COLUMNS) + " |")
        print("|---|" + "---:|" * len(COLUMNS))
        for name, m in systems.items():
            print(f"| {name} | " + " | ".join(f"{100 * m[key]:.1f}%" for key, _ in COLUMNS) + " |")
    return 0


def _impact(args) -> int:
    report = impact(generate_cases(args.cases, seed=0))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, indent=2))
    return 0


def _review(args) -> int:
    cases = {c.case_id: c for c in generate_cases(args.cases, seed=args.seed, heldout=args.heldout)}
    case = cases[args.case_id]
    for doc in case.evidence:
        print(f"[{doc.doc_id}] ({doc.kind}, issued {doc.issued}) {doc.text}")
    policy = POLICY_V2 if args.policy == POLICY_V2.version else POLICY_V1
    print(json.dumps(asdict(decide(case, policy)), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="riskbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="compare systems on development and held-out phrasing")
    ev.add_argument("--cases", type=int, default=1000)
    ev.add_argument("--out")
    ev.set_defaults(func=_evaluate)
    im = sub.add_parser("impact", help="shadow-run policy 2026.2 against 2026.1")
    im.add_argument("--cases", type=int, default=1000)
    im.add_argument("--out")
    im.set_defaults(func=_impact)
    rv = sub.add_parser("review", help="show one case's evidence and the cited decision")
    rv.add_argument("case_id")
    rv.add_argument("--cases", type=int, default=1000)
    rv.add_argument("--seed", type=int, default=0)
    rv.add_argument("--heldout", action="store_true")
    rv.add_argument("--policy", default=POLICY_V1.version)
    rv.set_defaults(func=_review)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
