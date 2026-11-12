"""Instruction -> draft mandate. The LLM only drafts; the user confirms; Python enforces."""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel

from ..config import env
from ..schemas import Clause, PurchaseIntent

NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


class ParseError(ValueError):
    pass


class _LLMClause(BaseModel):
    source_text: str
    rule: str


class _LLMIntent(BaseModel):
    product_keywords: list[str]
    max_total: str
    currency: str
    max_quantity: int
    approval_threshold: str
    merchants_from_user_list: bool
    clauses: list[_LLMClause]


def _default_merchants() -> list[str]:
    return [m.strip() for m in env("DEFAULT_APPROVED_MERCHANTS", "Best Buy,Newegg,Amazon").split(",") if m.strip()]


def _sentence(text: str, pos: int) -> str:
    start = max(text.rfind(".", 0, pos), text.rfind("?", 0, pos), text.rfind("!", 0, pos)) + 1
    ends = [i for i in (text.find(c, pos) for c in ".?!") if i != -1]
    return text[start:(min(ends) + 1 if ends else len(text))].strip()


def _build(text: str, kw, max_total, cur, qty, thr, merchants, clauses) -> PurchaseIntent:
    return PurchaseIntent(
        request_id="req-" + uuid.uuid4().hex[:10], raw_user_request=text, product_keywords=kw,
        max_total=max_total, currency=cur, max_quantity=qty, approval_threshold=thr,
        allowed_merchants=merchants, expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        single_use=True, clauses=[Clause(clause_id=f"C{i+1}", **c) for i, c in enumerate(clauses)],
    )


def parse_with_rules(text: str) -> PurchaseIntent:
    mt = re.search(r"(?:no more than|under|at most|up to|below|max(?:imum)?(?: of)?)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    ma = re.search(r"(?:ask me|check with me|confirm with me)[^.]*?(?:above|over|more than|exceeds?)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    mq = re.search(r"\b(?:buy|purchase|get|order)\s+(one|two|three|four|five|an?|\d+)\s+", text, re.I)
    mk = re.search(r"(?:buy|purchase|get|order)\s+(?:one|two|three|four|five|an?|\d+)\s+([a-z0-9 \-]+?)(?=\s+(?:for|under|no more|at most|from|only|below|up to)\b|[,.]|$)", text, re.I)
    ml = re.search(r"approved\s+(?:list|merchants?)|trusted\s+merchants?", text, re.I)
    if not (mt and mq and mk and ml):
        raise ParseError("Could not find a product, quantity, spend cap and approved-merchant rule. Rephrase.")
    q = mq.group(1).lower()
    qty = int(q) if q.isdigit() else NUM[q]
    total = Decimal(mt.group(1))
    thr = Decimal(ma.group(1)) if ma else total
    kw = [w.lower() for w in mk.group(1).split()]
    clauses = [
        {"source_text": _sentence(text, mk.start()), "rule": "product"},
        {"source_text": _sentence(text, mq.start()), "rule": "quantity"},
        {"source_text": _sentence(text, mt.start()), "rule": "max_total"},
        {"source_text": _sentence(text, ml.start()), "rule": "merchants"},
    ]
    if ma:
        clauses.append({"source_text": _sentence(text, ma.start()), "rule": "approval"})
    return _build(text, kw, total, "USD", qty, thr, _default_merchants(), clauses)


def parse_with_llm(text: str) -> PurchaseIntent:
    from openai import OpenAI
    r = OpenAI().beta.chat.completions.parse(
        model=env("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "Extract a purchase mandate. clauses[].source_text must be copied verbatim "
             "from the user text; rule is one of product,quantity,max_total,merchants,approval. "
             "Never invent limits the user did not state."},
            {"role": "user", "content": text}],
        response_format=_LLMIntent)
    p = r.choices[0].message.parsed
    if not p or not p.merchants_from_user_list:
        raise ParseError("LLM output incomplete")
    if any(c.source_text not in text or c.rule not in {"product", "quantity", "max_total", "merchants", "approval"}
           for c in p.clauses):
        raise ParseError("LLM clause not grounded in the user's words")
    return _build(text, [k.lower() for k in p.product_keywords], Decimal(p.max_total), p.currency.upper(),
                  p.max_quantity, Decimal(p.approval_threshold), _default_merchants(),
                  [c.model_dump() for c in p.clauses])


def parse_instruction(text: str) -> tuple[PurchaseIntent, str]:
    if env("OPENAI_API_KEY"):
        try:
            return parse_with_llm(text), "llm"
        except Exception:
            pass  # fall back to deterministic rules, never to guesses
    return parse_with_rules(text), "rules"
