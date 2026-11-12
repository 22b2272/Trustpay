"""TrustPay dashboard. Display only: every decision comes from the backend API."""
import os
import requests
import streamlit as st

API = os.environ.get("TRUSTPAY_API", "http://127.0.0.1:8000")
DEFAULT = ("Buy one mechanical keyboard for no more than $100. Only buy from a merchant on my approved list. "
           "Ask me before purchasing anything above $80.")
ICON = {"ALLOW": "🟢", "REVIEW": "🟡", "BLOCK": "🔴"}

st.set_page_config(page_title="TrustPay", page_icon="🛡️", layout="wide")
st.title("🛡️ TrustPay")
st.caption("Payment checks ask if a payment looks risky. TrustPay asks if your agent was actually allowed to make it.")


def api(method, path, **kw):
    r = requests.request(method, API + path, timeout=30, **kw)
    return r.status_code, (r.json() if r.content else {})


def receipt(rows):
    for r in rows:
        st.write(f"{'✅' if r['passed'] else '❌'} `{r['check']}` ← *{r['from_your_words']}*")


with st.sidebar:
    st.write("Backend:", API)
    if st.button("Check health"):
        st.write(api("GET", "/health")[1])

st.header("1. Your instruction becomes a mandate")
text = st.text_area("What should the agent buy?", DEFAULT, height=90)
if st.button("Draft mandate"):
    code, body = api("POST", "/intents/parse", json={"text": text})
    st.session_state["draft"] = body if code == 200 else None
    if code != 200:
        st.error(body.get("detail", body))
draft = st.session_state.get("draft")
if draft:
    st.caption(f"Parsed by: {draft['parser']}. Review before confirming.")
    st.json(draft["draft"])
    if st.button("Confirm mandate (single-use, 1 hour)"):
        code, body = api("POST", "/intents", json=draft["draft"])
        st.session_state["rid"] = draft["draft"]["request_id"] if code == 200 else None
        st.success(f"Mandate {st.session_state['rid']} saved") if code == 200 else st.error(body)

rid = st.session_state.get("rid")
if rid:
    st.header("2. Same agent, same poisoned page")
    scen = api("GET", "/demo/scenarios")[1]
    key = st.selectbox("Scenario", list(scen), format_func=lambda k: f"{k}: {scen[k]}")
    left, right = st.columns(2)
    with left:
        st.subheader("❌ Unprotected")
        if st.button("Run unprotected agent"):
            code, b = api("POST", "/demo/agent", json={"request_id": rid, "scenario": key, "protected": False})
            if code == 200:
                p = b["proposal"]
                st.error(f"Order created: {p['quantity']} × {p['product_name']} from {p['merchant_name']} "
                         f"@ {p['unit_price']} {p['currency']}")
                st.json(b["paypal_order"])
            else:
                st.warning(b)
    with right:
        st.subheader("🛡️ Behind TrustPay")
        if st.button("Run protected agent"):
            code, b = api("POST", "/demo/agent", json={"request_id": rid, "scenario": key, "protected": True})
            st.session_state["last"] = b if code == 200 else None
    last = st.session_state.get("last")
    if last:
        with right:
            st.markdown(f"### {ICON[last['decision']]} {last['decision']}  ·  {', '.join(last['reason_codes']) or 'no issues'}")
            st.write(last["explanation"])
            receipt(last["receipt"])
            pid = last["proposal_id"]
            if last["decision"] == "REVIEW" and st.button("I approve this purchase"):
                code, b = api("POST", f"/transactions/{pid}/approve")
                st.session_state["last"] = b if code == 200 else last
                st.rerun()
            if last.get("decision_token") and st.button("Execute via PayPal"):
                code, b = api("POST", f"/transactions/{pid}/execute", json={"token": last["decision_token"]})
                st.json(b)
                if b.get("simulated"):
                    st.warning("PayPal is SIMULATED in this run (PAYPAL_SIMULATE=1).")
            if st.checkbox("Audit trail"):
                st.json(api("GET", f"/transactions/{pid}")[1]["audit"])
