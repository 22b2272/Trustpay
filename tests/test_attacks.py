"""Red-team scoreboard: every attack must end in BLOCK or REVIEW (never ALLOW)."""
import pytest
from app.policy_engine import evaluate_transaction as ev

from app.redteam import ATTACKS, run_redteam


@pytest.mark.parametrize("name", ATTACKS)
def test_attack_not_allowed(intent, make_proposal, name):
    assert ev(intent, make_proposal(**ATTACKS[name])).decision != "ALLOW", name


def test_scoreboard(intent, make_proposal, capsys):
    res = {n: ev(intent, make_proposal(**kw)).decision.value for n, kw in ATTACKS.items()}
    blocked = sum(v == "BLOCK" for v in res.values()); review = sum(v == "REVIEW" for v in res.values())
    print(f"\nATTACKS {len(res)}: BLOCK {blocked}, REVIEW {review}, ALLOW {len(res)-blocked-review}")
    assert blocked + review == len(res)


def test_redteam_runner_matches_scoreboard():
    r = run_redteam()
    assert r["total"] == len(ATTACKS)
    assert r["unauthorized_allowed"] == 0
    assert r["block"] + r["review"] == r["total"]
    assert r["control_legit_purchase"] == "ALLOW"  # the gate is not just blocking everything
