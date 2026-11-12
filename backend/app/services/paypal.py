"""PayPal Orders v2 (sandbox). Only the execute gate in main.py may call this.
PAYPAL_SIMULATE=1 swaps in an in-memory fake; responses carry simulated=True so it is never passed off as real."""
import uuid
from decimal import Decimal

import httpx

from ..config import env


class PayPalError(Exception):
    pass


class PayPalSandbox:
    simulated = False

    def __init__(self):
        self.base = env("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        if "sandbox" not in self.base:
            raise PayPalError("refusing to use a non-sandbox PayPal URL")
        self.cid, self.secret = env("PAYPAL_CLIENT_ID"), env("PAYPAL_CLIENT_SECRET")
        if not (self.cid and self.secret):
            raise PayPalError("PayPal sandbox credentials not configured")

    def _req(self, method, path, json=None, request_id=None):
        try:
            with httpx.Client(timeout=20) as c:
                t = c.post(f"{self.base}/v1/oauth2/token", auth=(self.cid, self.secret),
                           data={"grant_type": "client_credentials"})
                t.raise_for_status()
                h = {"Authorization": f"Bearer {t.json()['access_token']}", "Content-Type": "application/json"}
                if request_id:
                    h["PayPal-Request-Id"] = request_id
                r = c.request(method, f"{self.base}{path}", json=json, headers=h)
                r.raise_for_status()
                return r.json() if r.content else {}
        except httpx.HTTPError as e:
            raise PayPalError(f"PayPal request failed: {e}") from e

    def create_order(self, proposal_id, merchant_norm, product, amount: Decimal, currency):
        body = {"intent": "AUTHORIZE", "purchase_units": [{
            "custom_id": f"{proposal_id}:{merchant_norm}",
            "description": product[:120],
            "amount": {"currency_code": currency, "value": f"{amount:.2f}"}}]}
        o = self._req("POST", "/v2/checkout/orders", body, request_id=f"order-{proposal_id}")
        link = next((l["href"] for l in o.get("links", []) if l["rel"] in ("approve", "payer-action")), None)
        return {"id": o["id"], "status": o["status"], "approve_url": link, "simulated": False}

    def get_order(self, order_id):
        return self._req("GET", f"/v2/checkout/orders/{order_id}")

    def authorize(self, order_id):
        o = self._req("POST", f"/v2/checkout/orders/{order_id}/authorize", {}, request_id=f"auth-{order_id}")
        return o["purchase_units"][0]["payments"]["authorizations"][0]["id"]

    def capture(self, auth_id):
        return self._req("POST", f"/v2/payments/authorizations/{auth_id}/capture", {}, request_id=f"cap-{auth_id}")


class PayPalSim:
    simulated = True

    def __init__(self):
        self._orders: dict = {}

    def create_order(self, proposal_id, merchant_norm, product, amount, currency):
        oid = "SIM-" + uuid.uuid4().hex[:12].upper()
        self._orders[oid] = {"id": oid, "status": "APPROVED",  # buyer approval is simulated
                             "purchase_units": [{"custom_id": f"{proposal_id}:{merchant_norm}",
                                                 "amount": {"currency_code": currency, "value": f"{amount:.2f}"}}]}
        return {"id": oid, "status": "APPROVED", "approve_url": None, "simulated": True}

    def get_order(self, order_id):
        return self._orders[order_id]

    def authorize(self, order_id):
        return "SIM-AUTH-" + order_id

    def capture(self, auth_id):
        return {"id": "SIM-CAP-" + auth_id, "status": "COMPLETED"}


_instance = None


def get_paypal():
    global _instance
    if _instance is None:
        _instance = PayPalSim() if env("PAYPAL_SIMULATE") == "1" else PayPalSandbox()
    return _instance


def reset():
    global _instance
    _instance = None
