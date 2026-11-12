"""LLM agent (mocked, no network), fallback behaviour, live red-team endpoint, and clause highlighting."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from app.services import agent  # noqa: E402
from highlight import highlight_instruction  # noqa: E402


def test_llm_agent_hijacked_proposal_is_still_blocked(client, monkeypatch):
    """Simulate an LLM that obeys the injected text. TrustPay must still BLOCK it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_llm_complete", lambda system, user: json.dumps(
        {"product_name": "Premium Bundle (3 keyboards + desk)", "quantity": 1, "unit_price": 449,
         "merchant_name": "SuperDeals Outlet"}))
    r = client.post("/demo/agent", json={"request_id": "req-test", "scenario": "D", "protected": True, "agent": "llm"})
    assert r.status_code == 200
    b = r.json()
    assert b["agent"] == "llm" and b["decision"] == "BLOCK"


def test_llm_agent_without_key_falls_back_and_says_so(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    b = client.post("/demo/agent", json={"request_id": "req-test", "scenario": "A", "protected": True, "agent": "llm"}).json()
    assert b["agent"] == "scripted" and "OPENAI_API_KEY" in b["agent_note"]
    assert b["decision"] == "ALLOW"


def test_llm_agent_garbage_output_falls_back(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(agent, "_llm_complete", lambda system, user: "not json")
    b = client.post("/demo/agent", json={"request_id": "req-test", "scenario": "A", "protected": True, "agent": "llm"}).json()
    assert b["agent"] == "scripted" and "failed" in b["agent_note"]


def test_redteam_endpoint(client):
    b = client.get("/demo/redteam").json()
    assert b["total"] == 16 and b["unauthorized_allowed"] == 0
    assert b["block"] + b["review"] == 16 and b["control_legit_purchase"] == "ALLOW"


def test_highlight_marks_violated_clause_red_and_escapes_html():
    text = "Buy one keyboard. Only buy from <b>approved</b> merchants."
    receipt = [{"check": "within_budget", "passed": True, "from_your_words": "Buy one keyboard."},
               {"check": "merchant_allowed", "passed": False, "from_your_words": "Only buy from <b>approved</b> merchants."}]
    out = highlight_instruction(text, receipt)
    assert "#cf222e" in out and "#1a7f37" in out          # one red, one green
    assert "violated: merchant_allowed" in out
    assert "<b>" not in out and "&lt;b&gt;" in out        # user text is escaped, never raw HTML


def test_highlight_ignores_phrases_not_in_text():
    out = highlight_instruction("hello", [{"check": "x", "passed": False, "from_your_words": "(built-in safety rule)"}])
    assert out == "hello"
