"""HMAC-SHA256 decision tokens over canonical JSON."""
import base64, hashlib, hmac, json, secrets
from datetime import datetime, timedelta, timezone

from .config import signing_key
from .policy_engine import norm_merchant
from .schemas import PurchaseIntent, TransactionProposal

TOKEN_TTL = timedelta(minutes=15)


class TokenError(Exception):
    pass


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def payload_for(intent: PurchaseIntent, p: TransactionProposal, decision: str, now: datetime) -> dict:
    exp = min(now + TOKEN_TTL, intent.expires_at)
    return {
        "request_id": p.request_id, "proposal_id": p.proposal_id, "decision": decision,
        "amount": f"{p.total_amount:.2f}", "currency": p.currency.upper(),
        "merchant": norm_merchant(p.merchant_name), "expires_at": exp.isoformat(),
        "nonce": secrets.token_hex(8),
    }


def sign(payload: dict) -> str:
    body = _canon(payload)
    return _b64(body) + "." + _b64(hmac.new(signing_key(), body, hashlib.sha256).digest())


def verify(token: str) -> dict:
    try:
        b, s = token.split(".")
        body, sig = _unb64(b), _unb64(s)
    except Exception as e:
        raise TokenError("malformed token") from e
    if not hmac.compare_digest(hmac.new(signing_key(), body, hashlib.sha256).digest(), sig):
        raise TokenError("bad signature")
    payload = json.loads(body)
    if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(timezone.utc):
        raise TokenError("token expired")
    return payload


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
