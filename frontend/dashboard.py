"""TrustPay dashboard. Display only: every decision comes from the backend API."""
import os

import requests
import streamlit as st

from highlight import highlight_instruction

API = os.environ.get("TRUSTPAY_API", "http://127.0.0.1:8000")
DEFAULT = ("Buy one mechanical keyboard for no more than $100. Only buy from a merchant on my approved list. "
           "Ask me before purchasing anything above $80.")
ICON = {"ALLOW": "🟢", "REVIEW": "🟡", "BLOCK": "🔴"}
PLAIN = {
    "ALLOW": "Allowed. Inside everything you asked for.",
    "REVIEW": "Needs your approval. It is allowed, but you said to ask first.",
    "BLOCK": "Blocked. This is not what you asked for. No money moves.",
}

st.set_page_config(page_title="TrustPay", page_icon="🛡️", layout="wide")
st.title("🛡️ TrustPay")
st.caption("Payment checks ask if a payment looks risky. TrustPay asks if your agent was actually allowed to make it.")


def api(method, path, **kw):
    try:
        r = requests.request(method, API + path, timeout=30, **kw)
        return r.status_code, (r.json() if r.content else {})
    except requests.exceptions.RequestException:
        st.error(f"Cannot reach the backend at {API}. Start it with: uvicorn app.main:app --reload (from the backend folder).")
        st.stop()


def verdict_banner(decision, reasons):
    text = f"{ICON[decision]} **{decision}**: {PLAIN[decision]}"
    if reasons:
        text += f"  \nWhy: {', '.join(reasons)}"
    {"ALLOW": st.success, "REVIEW": st.warning, "BLOCK": st.error}[decision](text)


def receipt(rows, instruction=""):
    if instruction:
        st.markdown("**Your own words, checked** (green = followed, red = violated)")
        st.markdown(highlight_instruction(instruction, rows), unsafe_allow_html=True)
    with st.expander("Check-by-check receipt", expanded=True):
        for row in rows:
            st.write(f"{'✅' if row['passed'] else '❌'} `{row['check']}` ← *{row['from_your_words']}*")


def reset_demo():
    for key in ("draft", "rid", "instruction", "unprot", "last", "last_key", "exec"):
        st.session_state.pop(key, None)


with st.sidebar:
    st.subheader("Red-team scoreboard")
    st.caption("Fires every built-in attack at the real policy engine.")
    if st.button("Run all attacks", use_container_width=True):
        code, result = api("GET", "/demo/redteam")
        if code == 200:
            st.session_state["redteam"] = result
        else:
            st.error(result)
    redteam = st.session_state.get("redteam")
    if redteam:
        c1, c2 = st.columns(2)
        c1.metric("Attacks tried", redteam["total"])
        c2.metric("Unauthorized ALLOW", redteam["unauthorized_allowed"])
        st.write(f"🔴 BLOCK {redteam['block']} · 🟡 REVIEW {redteam['review']}")
        st.write(f"Control (legit $65 purchase): **{redteam['control_legit_purchase']}**")
        with st.expander("Every attack"):
            for row in redteam["results"]:
                st.write(f"{ICON[row['decision']]} `{row['attack']}` → {', '.join(row['reasons'])}")
    st.divider()
    if st.button("Start over", use_container_width=True):
        reset_demo()
        st.rerun()
    with st.expander("Backend"):
        st.write(API)
        if st.button("Check health"):
            code, result = api("GET", "/health")
            st.success(result) if code == 200 else st.error(result)

st.info(
    "**How this demo works**  \n"
    "**1.** Write what your agent may buy. It becomes a one-time rule set (a mandate).  \n"
    "**2.** Run the *same* hijacked agent twice: once with no protection, once behind TrustPay.  \n"
    "**3.** See the verdict and the receipt that ties every check to your own words."
)

st.header("Step 1 · Tell the agent what it may buy")
text = st.text_area("Your instruction, in plain English", DEFAULT, height=90)
if st.button("Draft mandate", type="primary"):
    code, body = api("POST", "/intents/parse", json={"text": text})
    st.session_state["draft"] = body if code == 200 else None
    if code != 200:
        st.error(body.get("detail", body))

draft = st.session_state.get("draft")
if draft and not st.session_state.get("rid"):
    mandate = draft["draft"]
    st.caption(f"Drafted by: {draft['parser']}. Check it, then confirm.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Max total", f"{mandate['max_total']} {mandate['currency']}")
    m2.metric("Max quantity", mandate["max_quantity"])
    m3.metric("Ask me above", f"{mandate['approval_threshold']} {mandate['currency']}")
    m4.metric("Approved merchants", len(mandate["allowed_merchants"]))
    st.write("**Approved merchants:** " + (", ".join(mandate["allowed_merchants"]) or "none (everything will be blocked)"))
    with st.expander("Full mandate (technical)"):
        st.json(mandate)
    if st.button("Confirm mandate (single-use, 1 hour)", type="primary"):
        code, body = api("POST", "/intents", json=mandate)
        st.session_state["rid"] = mandate["request_id"] if code == 200 else None
        st.session_state["instruction"] = mandate["raw_user_request"]
        if code == 200:
            st.rerun()
        else:
            st.error(body)

rid = st.session_state.get("rid")
if rid:
    st.success(f"✅ Mandate confirmed ({rid}). Now try to break it.")
    st.header("Step 2 · Same agent, same poisoned page")
    code, scenarios = api("GET", "/demo/scenarios")
    if code != 200:
        st.error(scenarios)
        st.stop()
    key = st.radio("Pick an attack or purchase", list(scenarios),
                   format_func=lambda k: f"{k}: {scenarios[k]}", horizontal=True)
    with st.expander("Advanced: choose the agent"):
        agent_mode = st.radio("Agent", ["scripted", "llm"], horizontal=True,
                              format_func=lambda mode: "Scripted (no API key)" if mode == "scripted" else "Real LLM (OpenAI)")

    left, right = st.columns(2)
    with left:
        st.subheader("❌ Without TrustPay")
        st.caption("The agent obeys whatever the page says.")
        if st.button("Run unprotected agent", use_container_width=True):
            code, body = api("POST", "/demo/agent", json={
                "request_id": rid, "scenario": key, "protected": False, "agent": agent_mode,
            })
            st.session_state["unprot"] = (key, body) if code == 200 else None
            if code != 200:
                st.error(body)
        unprotected = st.session_state.get("unprot")
        if unprotected and unprotected[0] == key:
            body = unprotected[1]
            proposal = body["proposal"]
            st.caption(f"Agent used: {body['agent']}" +
                       (f" ({body['agent_note']})" if body["agent_note"] else ""))
            st.error(f"💸 Order created: {proposal['quantity']} × {proposal['product_name']} "
                     f"from {proposal['merchant_name']} @ {proposal['unit_price']} {proposal['currency']}")
            with st.expander("PayPal order"):
                st.json(body["paypal_order"])

    with right:
        st.subheader("🛡️ Behind TrustPay")
        st.caption("Every purchase is checked against your mandate first.")
        if st.button("Run protected agent", type="primary", use_container_width=True):
            code, body = api("POST", "/demo/agent", json={
                "request_id": rid, "scenario": key, "protected": True, "agent": agent_mode,
            })
            st.session_state["last"] = body if code == 200 else None
            st.session_state["last_key"] = key
            st.session_state["exec"] = None
            if code != 200:
                st.error(body)

        last = st.session_state.get("last")
        if last and st.session_state.get("last_key") == key:
            st.caption(f"Agent used: {last.get('agent', 'scripted')}" +
                       (f" ({last['agent_note']})" if last.get("agent_note") else ""))
            verdict_banner(last["decision"], last["reason_codes"])
            st.write(last["explanation"])
            receipt(last["receipt"], st.session_state.get("instruction", ""))
            proposal_id = last["proposal_id"]

            if last["decision"] == "REVIEW" and st.button("I approve this purchase", use_container_width=True):
                code, body = api("POST", f"/transactions/{proposal_id}/approve")
                st.session_state["last"] = body if code == 200 else last
                if code != 200:
                    st.error(body)
                st.rerun()

            if last.get("decision_token"):
                st.markdown("**Step 3 · Pay**")
                if st.button("Execute via PayPal", type="primary", use_container_width=True):
                    code, body = api("POST", f"/transactions/{proposal_id}/execute",
                                     json={"token": last["decision_token"]})
                    st.session_state["exec"] = body
                    if code != 200:
                        st.error(body)

                execution = st.session_state.get("exec")
                if execution:
                    if execution.get("status") == "PAYER_ACTION_REQUIRED" and execution.get("approve_url"):
                        st.info("PayPal needs the sandbox buyer to approve first. Click the button, approve, "
                                "then come back and press **Finish payment**.")
                        st.link_button("1. Approve in PayPal sandbox", execution["approve_url"],
                                       use_container_width=True)
                        if st.button("2. I approved it, finish payment", use_container_width=True):
                            code, body = api("POST", f"/transactions/{proposal_id}/execute",
                                             json={"token": last["decision_token"]})
                            st.session_state["exec"] = body
                            if code != 200:
                                st.error(body)
                            st.rerun()
                    elif execution.get("status") == "COMPLETED":
                        st.success(f"💳 Payment completed.  \nPayPal order: `{execution['paypal_order_id']}`  \n"
                                   f"Capture: `{execution.get('capture_id', '-')}`")
                        if execution.get("simulated"):
                            st.warning("PayPal is SIMULATED in this run (PAYPAL_SIMULATE=1). Not a real sandbox payment.")
                        else:
                            st.caption("Real PayPal sandbox payment (not simulated).")
                    with st.expander("Raw PayPal response"):
                        st.json(execution)

            if st.checkbox("Show audit trail"):
                code, body = api("GET", f"/transactions/{proposal_id}")
                if code == 200:
                    st.json(body["audit"])
                else:
                    st.error(body)
