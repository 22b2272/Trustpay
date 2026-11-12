from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class Clause(BaseModel):
    clause_id: str
    source_text: str  # exact words from the user's instruction
    rule: str  # product | max_total | quantity | merchants | approval


class PurchaseIntent(BaseModel):
    request_id: str
    raw_user_request: str
    product_keywords: list[str]
    max_total: Decimal
    currency: str = "USD"
    max_quantity: int
    approval_threshold: Decimal
    allowed_merchants: list[str]
    expires_at: datetime
    single_use: bool = True
    clauses: list[Clause] = Field(default_factory=list)

    @field_validator("expires_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class TransactionProposal(BaseModel):
    proposal_id: str
    request_id: str
    product_name: str
    quantity: int
    unit_price: Decimal
    currency: str = "USD"
    merchant_name: str
    # untrusted text: scanned as data, never treated as policy
    product_description: str = ""
    agent_context: str = ""

    @property
    def total_amount(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))


class Check(BaseModel):
    check: str
    passed: bool
    clause_id: str


class PolicyDecision(BaseModel):
    decision: Decision
    reason_codes: list[str]
    checks: list[Check]
    explanation: str
    policy_version: str
    evaluated_at: datetime
