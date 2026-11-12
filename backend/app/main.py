import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import db, token as tok
from .policy_engine import build_receipt, evaluate_transaction, norm_merchant
from .redteam import run_redteam
from .schemas import Decision, PurchaseIntent, TransactionProposal
from .services import agent
from .services.intent_parser import ParseError, parse_instruction
from .services.paypal import PayPalError, get_paypal

app = FastAPI(title="TrustPay", description="Intent-aware authorization gate for AI shopping agents")


def _now():
    return datetime.now(timezone.utc)


def _load_intent(rid: str) -> PurchaseIntent:
    row = db.one("SELECT parsed_json FROM intents WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "unknown mandate")  # fail closed
    return PurchaseIntent.model_validate_json(row["parsed_json"])


def _load_proposal(pid: str):
    row = db.one("SELECT * FROM proposals WHERE id=?", (pid,))
    if not row:
        raise HTTPException(404, "unknown proposal")
    return row, TransactionProposal.model_validate_json(row["proposal_json"])


def _issue(intent, p, decision: str) -> str:
    t = tok.sign(tok.payload_for(intent, p, decision, _now()))
    db.run("UPDATE proposals SET token_hash=? WHERE id=?", (tok.token_hash(t), p.proposal_id))
    db.audit(p.proposal_id, "token_issued", {"decision": decision})
    return t


class ParseBody(BaseModel):
    text: str


class ApproveBody(BaseModel):
    approver: str = "user"


class ExecuteBody(BaseModel):
    token: str
    decision: str | None = None  # ignored on purpose: the server reloads the stored decision


class DemoBody(BaseModel):
    request_id: str
    scenario: str
    protected: bool = True
    agent: str = "scripted"  # "scripted" or "llm" (real OpenAI agent, falls back if no key)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/intents/parse")
def parse_intent(b: ParseBody):
    try:
        intent, parser = parse_instruction(b.text)
    except ParseError as e:
        raise HTTPException(422, str(e))
    return {"draft": intent.model_dump(mode="json"), "parser": parser}


@app.post("/intents")
def save_intent(intent: PurchaseIntent):
    if intent.expires_at <= _now():
        raise HTTPException(422, "mandate already expired")
    db.run("INSERT OR REPLACE INTO intents(id,raw_text,parsed_json,confirmed_at,expires_at) VALUES(?,?,?,?,?)",
           (intent.request_id, intent.raw_user_request, intent.model_dump_json(), db.now_iso(),
            intent.expires_at.isoformat()))
    db.audit(None, "mandate_confirmed", {"request_id": intent.request_id})
    return {"request_id": intent.request_id}


def _view(intent, p, d, status, token=None):
    return {"proposal_id": p.proposal_id, "decision": d.decision.value, "status": status,
            "reason_codes": d.reason_codes, "explanation": d.explanation,
            "receipt": build_receipt(intent, d), "decision_token": token}


@app.post("/transactions/evaluate")
def evaluate(p: TransactionProposal):
    intent = _load_intent(p.request_id)
    if db.one("SELECT id FROM proposals WHERE id=?", (p.proposal_id,)):
        raise HTTPException(409, "proposal_id already used")
    d = evaluate_transaction(intent, p)
    status = {Decision.ALLOW: "allowed", Decision.REVIEW: "pending_review", Decision.BLOCK: "blocked"}[d.decision]
    db.run("INSERT INTO proposals(id,intent_id,proposal_json,decision,reason_codes,status,created_at) VALUES(?,?,?,?,?,?,?)",
           (p.proposal_id, p.request_id, p.model_dump_json(), d.decision.value, json.dumps(d.reason_codes),
            status, db.now_iso()))
    db.audit(p.proposal_id, "evaluated", {"decision": d.decision.value, "reasons": d.reason_codes,
                                          "checks": [c.model_dump() for c in d.checks]})
    t = _issue(intent, p, "ALLOW") if d.decision == Decision.ALLOW else None
    return _view(intent, p, d, status, t)


@app.post("/transactions/{pid}/approve")
def approve(pid: str, b: ApproveBody = ApproveBody()):
    row, p = _load_proposal(pid)
    if row["decision"] == "BLOCK" or row["status"] == "blocked":
        db.audit(pid, "approve_rejected", {"why": "BLOCK cannot be overridden"})
        raise HTTPException(403, "BLOCK cannot be overridden")
    if row["status"] != "pending_review":
        raise HTTPException(409, f"proposal is {row['status']}, not pending review")
    intent = _load_intent(p.request_id)
    d = evaluate_transaction(intent, p, approved=True)  # full re-evaluation, never trust the old result
    if d.decision != Decision.ALLOW:
        db.run("UPDATE proposals SET decision=?, status='blocked' WHERE id=?", (d.decision.value, pid))
        db.audit(pid, "approve_rejected", {"reasons": d.reason_codes})
        raise HTTPException(403, {"error": "no longer allowed", "reasons": d.reason_codes})
    db.run("UPDATE proposals SET decision='ALLOW', status='approved', reason_codes=? WHERE id=?",
           (json.dumps(d.reason_codes), pid))
    db.audit(pid, "human_approved", {"approver": b.approver})
    return _view(intent, p, d, "approved", _issue(intent, p, "ALLOW"))


def _order_mismatch(order: dict, p: TransactionProposal) -> list[str]:
    pu = order["purchase_units"][0]
    bad = []
    if Decimal(str(pu["amount"]["value"])) != p.total_amount:
        bad.append("amount")
    if pu["amount"]["currency_code"].upper() != p.currency.upper():
        bad.append("currency")
    if pu.get("custom_id") != f"{p.proposal_id}:{norm_merchant(p.merchant_name)}":
        bad.append("merchant_or_proposal")
    return bad


@app.post("/transactions/{pid}/execute")
def execute(pid: str, b: ExecuteBody):
    row, p = _load_proposal(pid)  # decision comes from the DB, never from the client
    intent = _load_intent(p.request_id)

    def reject(code, msg, extra=None):
        db.audit(pid, "execute_rejected", {"code": code, "msg": msg, **(extra or {})})
        raise HTTPException(code, {"error": msg, **(extra or {})})

    if row["decision"] != "ALLOW" or row["status"] not in ("allowed", "approved", "executing", "completed"):
        reject(403, f"not executable (status={row['status']}, decision={row['decision']})")
    try:
        pl = tok.verify(b.token)
    except tok.TokenError as e:
        reject(401, f"invalid token: {e}")
    expect = {"request_id": p.request_id, "proposal_id": pid, "decision": "ALLOW",
              "amount": f"{p.total_amount:.2f}", "currency": p.currency.upper(),
              "merchant": norm_merchant(p.merchant_name)}
    if any(pl.get(k) != v for k, v in expect.items()) or tok.token_hash(b.token) != row["token_hash"]:
        reject(403, "token does not match the stored proposal")
    if intent.expires_at <= _now():
        reject(403, "mandate expired")
    if intent.single_use and db.run("UPDATE intents SET used_by=? WHERE id=? AND (used_by IS NULL OR used_by=?)",
                                    (pid, intent.request_id, pid)) == 0:
        reject(409, "single-use mandate already spent on another proposal")

    ex = db.one("SELECT * FROM executions WHERE proposal_id=?", (pid,))
    if ex and ex["paypal_status"] == "COMPLETED":  # duplicate / replay: one order only
        return {"status": "COMPLETED", "paypal_order_id": ex["paypal_order_id"], "idempotent": True,
                "simulated": get_paypal().simulated}
    try:
        pp = get_paypal()
        if not ex:
            o = pp.create_order(pid, norm_merchant(p.merchant_name), p.product_name, p.total_amount, p.currency)
            db.run("INSERT INTO executions(proposal_id,paypal_order_id,paypal_status) VALUES(?,?,?)",
                   (pid, o["id"], o["status"]))
            db.run("UPDATE proposals SET status='executing' WHERE id=?", (pid,))
            db.audit(pid, "paypal_order_created", {"order_id": o["id"], "simulated": pp.simulated})
            oid = o["id"]
        else:
            oid = ex["paypal_order_id"]
        order = pp.get_order(oid)
        bad = _order_mismatch(order, p)  # re-check what PayPal actually holds before any capture
        if bad:
            db.run("UPDATE executions SET paypal_status='REJECTED' WHERE proposal_id=?", (pid,))
            reject(409, "PayPal order does not match the approved proposal", {"mismatch": bad})
        if order["status"] != "APPROVED":
            return {"status": "PAYER_ACTION_REQUIRED", "paypal_order_id": oid,
                    "approve_url": next((l["href"] for l in order.get("links", []) if l["rel"] in ("approve", "payer-action")), None),
                    "note": "Buyer must approve in sandbox, then call execute again with the same token."}
        cap = pp.capture(pp.authorize(oid))
    except PayPalError as e:
        db.audit(pid, "paypal_error", {"error": str(e)})
        if not db.one("SELECT 1 AS x FROM executions WHERE proposal_id=?", (pid,)):
            db.run("UPDATE intents SET used_by=NULL WHERE id=? AND used_by=?", (intent.request_id, pid))
        raise HTTPException(502, "PayPal error, nothing captured")
    db.run("UPDATE executions SET paypal_status=? WHERE proposal_id=?", (cap["status"], pid))
    db.run("UPDATE proposals SET status=? WHERE id=?", ("completed" if cap["status"] == "COMPLETED" else "executing", pid))
    db.audit(pid, "paypal_captured", {"order_id": oid, "status": cap["status"], "simulated": pp.simulated})
    return {"status": cap["status"], "paypal_order_id": oid, "capture_id": cap["id"], "simulated": pp.simulated}


@app.get("/transactions/{pid}")
def get_transaction(pid: str):
    row, p = _load_proposal(pid)
    intent = _load_intent(p.request_id)
    d = evaluate_transaction(intent, p, approved=row["status"] in ("approved", "executing", "completed"))
    return {"proposal": p.model_dump(mode="json"), "decision": row["decision"], "status": row["status"],
            "reason_codes": json.loads(row["reason_codes"]), "receipt": build_receipt(intent, d),
            "execution": db.one("SELECT * FROM executions WHERE proposal_id=?", (pid,)),
            "audit": db.many("SELECT event_type, detail_json, timestamp FROM audit_events WHERE proposal_id=? ORDER BY id", (pid,))}


@app.get("/demo/scenarios")
def scenarios():
    return agent.SCENARIO_LABELS


@app.get("/demo/redteam")
def redteam():
    """Live scoreboard: runs every built-in attack through the real policy engine."""
    return run_redteam()


@app.post("/demo/agent")
def demo_agent(b: DemoBody):
    if b.scenario not in agent.DEMO_PAGES:
        raise HTTPException(404, "unknown scenario")
    intent = _load_intent(b.request_id)
    p, used, note = agent.propose_auto(agent.DEMO_PAGES[b.scenario], b.request_id, intent.raw_user_request, b.agent)
    info = {"agent": used, "agent_note": note}
    if b.protected:
        return {"mode": "PROTECTED", **info, "proposal": p.model_dump(mode="json"), **evaluate(p)}
    # UNPROTECTED demo path: what a naive agent would do. Deliberately bypasses the gate; demo only.
    try:
        o = get_paypal().create_order(p.proposal_id, norm_merchant(p.merchant_name), p.product_name,
                                      p.total_amount, p.currency)
    except PayPalError as e:
        raise HTTPException(502, str(e))
    db.audit(p.proposal_id, "UNPROTECTED_demo_order", {"order_id": o["id"], "total": str(p.total_amount)})
    return {"mode": "UNPROTECTED", **info, "proposal": p.model_dump(mode="json"), "paypal_order": o,
            "note": "No authorization check. The agent's hijacked purchase went straight to PayPal."}
