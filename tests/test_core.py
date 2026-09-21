import unittest

from risk_agent_workbench.core import Case, Evidence, PolicyRule, VersionedPolicyStore, fixture


class RiskTests(unittest.TestCase):
    def test_fixture_decisions(self):
        analyst, cases = fixture()
        for case, expected in cases:
            self.assertEqual(analyst.analyze(case)["decision"], expected)

    def test_findings_are_cited(self):
        analyst, cases = fixture()
        report = analyst.analyze(cases[1][0])
        self.assertTrue(report["findings"][0]["citations"])

    def test_missing_evidence_abstains(self):
        analyst, cases = fixture()
        report = analyst.analyze(cases[-1][0])
        self.assertEqual(report["decision"], "needs_evidence")
        self.assertEqual(report["missing_sources"], ["registry"])

    def test_versions_are_immutable(self):
        store = VersionedPolicyStore()
        store.publish("v1", [PolicyRule("r", ("x",), 1, (), "x")])
        with self.assertRaises(ValueError):
            store.publish("v1", [])


if __name__ == "__main__":
    unittest.main()
