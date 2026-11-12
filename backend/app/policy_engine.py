"""Deterministic policy engine. No LLM in here. Money is Decimal."""
import re
from datetime import datetime, timezone
from decimal import Decimal

from .risk_signals import scan
from .schemas import Check, Decision, PolicyDecision, PurchaseIntent, TransactionProposal

POLICY_VERSION = "2026.11.1"


def norm_merchant(name: str) -> str:
    """'BestBuy ' and 'Best Buy' match; 'Bestbuy-deals' does not."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _clause_id(intent: PurchaseIntent, rule: str) -> str:
    return next((c.clause_id for c in intent.clauses if c.rule == rule), "implicit")


def evaluate_transaction(
    intent: PurchaseIntent,
    p: TransactionProposal,
    now: datetime | None = None,
    approved: bool = False,
) -> PolicyDecision:
    now = now or datetime.now(timezone.utc)
    checks: list[Check] = []
    hard: list[str] = []
    soft: list[str] = []

    def chk(name: str, ok: bool, rule: str, code: str, kind: str = "hard") -> None:
        checks.append(Check(check=name, passed=bool(ok), clause_id=_clause_id(intent, rule)))
        if not ok:
            (hard if kind == "hard" else soft).append(code)

    merchants = {norm_merchant(m) for m in intent.allowed_merchants} - {""}
    total = p.total_amount

    complete = (
        intent.max_total > 0 and intent.max_quantity > 0 and intent.approval_threshold > 0
        and bool(merchants) and bool(intent.product_keywords) and bool(intent.currency)
    )
    chk("mandate_complete", complete, "implicit", "MANDATE_INCOMPLETE")
    chk("mandate_not_expired", intent.expires_at > now, "implicit", "MANDATE_EXPIRED")
    chk("currency_matches", p.currency.upper() == intent.currency.upper(), "max_total", "CURRENCY_MISMATCH")
    chk("quantity_within_limit", 0 < p.quantity <= intent.max_quantity, "quantity", "QUANTITY_MISMATCH")
    chk("price_positive", p.unit_price > 0, "max_total", "INVALID_AMOUNT")
    chk("within_budget", total <= intent.max_total, "max_total", "OVER_BUDGET")
    chk("merchant_allowed", norm_merchant(p.merchant_name) in merchants, "merchants", "MERCHANT_NOT_ALLOWED")
    name = p.product_name.lower()
    chk("product_matches", bool(intent.product_keywords) and all(k.lower() in name for k in intent.product_keywords),
        "product", "PRODUCT_MISMATCH")
    chk("under_approval_threshold", total <= intent.approval_threshold, "approval",
        "OVER_APPROVAL_THRESHOLD", kind="soft")
    signals = scan(p.product_name, p.product_description, p.agent_context)
    chk("no_injection_signals", not signals, "implicit", "INJECTION_SUSPECTED", kind="soft")

    if hard:
        decision, reasons = Decision.BLOCK, hard + soft
    elif soft and not approved:
        decision, reasons = Decision.REVIEW, soft
    else:
        decision, reasons = Decision.ALLOW, (["HUMAN_APPROVED"] if soft else [])

    return PolicyDecision(
        decision=decision, reason_codes=reasons, checks=checks,
        explanation=_explain(decision, reasons, total, p), policy_version=POLICY_VERSION, evaluated_at=now,
    )


def _explain(decision: Decision, reasons: list[str], total: Decimal, p: TransactionProposal) -> str:
    base = f"{p.quantity} x {p.product_name} from {p.merchant_name}, total {total} {p.currency}."
    if decision == Decision.ALLOW:
        return f"{base} Within the mandate."
    return f"{base} {decision.value}: {', '.join(reasons)}."


def build_receipt(intent: PurchaseIntent, d: PolicyDecision) -> list[dict]:
    """Every check linked back to the user's own words."""
    text = {c.clause_id: c.source_text for c in intent.clauses}
    return [
        {"check": c.check, "passed": c.passed, "clause_id": c.clause_id,
         "from_your_words": text.get(c.clause_id, "(built-in safety rule)")}
        for c in d.checks
    ]
