#!/usr/bin/env python3
"""Unit tests for the scoring and statistics code that produces the numbers of paper 23 (rigor item X18).

    python3 analysis/test_scoring.py          # stdlib unittest, no pytest needed; about 3 s

Every expected value is worked out by hand in the comment beside it. These cover the code in this folder
(outcome categories, rank correlation, exact permutation p, critical value, Clopper-Pearson interval, hidden-score
denominators, diff filtering). They do not cover the organisers' scorer, which decides whether a task is solved and is
not available to us, nor the competition repository's own tests (tests/test_golden_metrics.py and
tests/test_a6000_run_eval.py), which need pytest and were not run for this version.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calibration_robustness as cr  # noqa: E402
import decision_checks as dc  # noqa: E402
import run_inventory as ri  # noqa: E402


class Scoring(unittest.TestCase):
    def test_outcome_categories(self):
        # solved wins over everything; no patch vs patch; "timeout" in err means the per-task cap was hit
        self.assertEqual(ri.category({"resolved": True, "patch": "x", "err": "Agent exceeded session timeout"}), "solved")
        self.assertEqual(ri.category({"resolved": False, "patch": "", "err": None}), "empty patch, ended early")
        self.assertEqual(ri.category({"resolved": False, "patch": None, "err": "session timeout (5.0 min)"}), "empty patch, cap hit")
        self.assertEqual(ri.category({"resolved": False, "patch": "diff", "err": ""}), "patch fails, ended early")
        self.assertEqual(ri.category({"resolved": False, "patch": "diff", "err": "timeout"}), "patch fails, cap hit")

    def test_rank_correlation_hand_cases(self):
        self.assertAlmostEqual(cr.rho([1, 2, 3], [10, 20, 30]), 1.0)       # same order
        self.assertAlmostEqual(cr.rho([1, 2, 3], [3, 2, 1]), -1.0)         # reversed
        # ties: x ranks 1.5,1.5,3.5,3.5 and y ranks 1.5,3.5,1.5,3.5 -> deviations (-1,-1,1,1) and (-1,1,-1,1): sum of products 0
        self.assertAlmostEqual(cr.rho([1, 1, 2, 2], [1, 2, 1, 2]), 0.0)

    def test_exact_permutation_p(self):
        # n=3: |rho|=1 for 2 of the 3! = 6 orderings -> 1/3
        self.assertAlmostEqual(cr.exact_perm_p([1, 2, 3], [1, 2, 3], cr.rho), 2 / 6)
        # n=4: 2 of 24 -> 0.0833, the paper's "smallest attainable exact p with four points"
        self.assertAlmostEqual(cr.exact_perm_p([1, 2, 3, 4], [1, 2, 3, 4], cr.rho), 2 / 24)

    def test_critical_values(self):
        # published exact two-sided 0.05 critical Spearman value for n=7 is 0.786 (= 1 - 6*12/(7*48))
        self.assertAlmostEqual(cr.critical_rho(7), 0.7857, places=3)
        self.assertEqual(cr.critical_rho(4), 1.0)                           # no value reaches p <= 0.05 at n=4

    def test_clopper_pearson(self):
        lo, hi = dc.clopper_pearson(2, 2)                                   # lower bound = (0.025)^(1/2) = 0.1581, upper = 1
        self.assertAlmostEqual(lo, 0.025 ** 0.5, places=6)
        self.assertEqual(hi, 1.0)
        lo, hi = dc.clopper_pearson(0, 5)                                   # lower 0, upper = 1 - 0.025^(1/5) = 0.4782
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** 0.2, places=6)

    def test_hidden_scores_are_k_over_60(self):
        # the printed scores and the task counts the paper uses: 0.05=3, 0.08=5, 0.10=6, 0.13=8, 0.15=9, 0.17=10
        for k, s in [(3, 0.05), (5, 0.08), (6, 0.10), (8, 0.13), (9, 0.15), (10, 0.17)]:
            self.assertEqual(round(k / 60, 2), s)
        self.assertEqual(cr.denominator_check([0.05, 0.08, 0.1, 0.13, 0.15, 0.17])["denominators_55_to_63_consistent_with_every_score"], [60])

    def test_added_lines_filter(self):
        diff = "+++ b/x.py\n+short\n+    assert response.status_code == 200, response.text\n+# a long comment line that is more than forty chars long\n-removed line that is long enough to count but is removed\n"
        self.assertEqual(dc.added_lines(diff), {"assert response.status_code == 200, response.text"})   # only the 40+ char code line added

    def test_new_test_files(self):
        diff = "--- /dev/null\n+++ b/tests/test_new.py\n+x\n--- a/tests/test_old.py\n+++ b/tests/test_old.py\n"
        self.assertEqual(dc.new_test_files(diff), {"tests/test_new.py"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
