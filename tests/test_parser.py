import pytest
from decimal import Decimal
from app.services.intent_parser import ParseError, parse_with_rules
from conftest import INSTRUCTION


def test_parses_demo_instruction():
    i = parse_with_rules(INSTRUCTION)
    assert i.product_keywords == ["mechanical", "keyboard"] and i.max_total == Decimal("100")
    assert i.max_quantity == 1 and i.approval_threshold == Decimal("80")
    assert all(c.source_text in INSTRUCTION for c in i.clauses) and {c.rule for c in i.clauses} >= {"product", "approval", "merchants"}


@pytest.mark.parametrize("t", ["buy me something nice", "Buy one keyboard. Only from approved merchants.", ""])
def test_unclear_instruction_fails_closed(t):
    with pytest.raises(ParseError):
        parse_with_rules(t)
