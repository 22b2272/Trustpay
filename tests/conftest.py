import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.update(DECISION_SIGNING_KEY="test-signing-key-0123456789", PAYPAL_SIMULATE="1", OPENAI_API_KEY="")

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi.testclient import TestClient

from app.schemas import Clause, PurchaseIntent, TransactionProposal

INSTRUCTION = ("Buy one mechanical keyboard for no more than $100. Only buy from a merchant on my approved list. "
               "Ask me before purchasing anything above $80.")


@pytest.fixture
def intent():
    return PurchaseIntent(
        request_id="req-test", raw_user_request=INSTRUCTION, product_keywords=["mechanical", "keyboard"],
        max_total=Decimal("100"), currency="USD", max_quantity=1, approval_threshold=Decimal("80"),
        allowed_merchants=["Best Buy", "Newegg"], expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        clauses=[Clause(clause_id="C1", source_text="Buy one mechanical keyboard for no more than $100.", rule="product"),
                 Clause(clause_id="C2", source_text="Buy one mechanical keyboard for no more than $100.", rule="max_total"),
                 Clause(clause_id="C3", source_text="Only buy from a merchant on my approved list.", rule="merchants"),
                 Clause(clause_id="C4", source_text="Ask me before purchasing anything above $80.", rule="approval"),
                 Clause(clause_id="C5", source_text="Buy one mechanical keyboard for no more than $100.", rule="quantity")])


@pytest.fixture
def make_proposal():
    n = [0]
    def f(**kw):
        n[0] += 1
        d = dict(proposal_id=f"prop-{n[0]}-{os.urandom(3).hex()}", request_id="req-test",
                 product_name="Mechanical Keyboard", quantity=1, unit_price=Decimal("65"), currency="USD",
                 merchant_name="Best Buy")
        d.update(kw)
        return TransactionProposal(**d)
    return f


@pytest.fixture
def client(tmp_path, monkeypatch, intent):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    from app.services import paypal
    paypal.reset()
    from app.main import app
    c = TestClient(app)
    assert c.post("/intents", content=intent.model_dump_json(), headers={"content-type": "application/json"}).status_code == 200
    return c
