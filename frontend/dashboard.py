"""TrustPay dashboard. Display only: every decision comes from the backend API."""
import os
import requests
import streamlit as st

from highlight import highlight_instruction

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


def receipt(rows, instruction=""):
    if instruction:
        st.markdown("**Your instruction, checked:**")
        st.markdown(highlight_instruction(instruction, rows), unsafe_allow_html=True)
    for r in rows:
        st.write(f"{'✅' if r['passed'] else '❌'} `{r['check']}` ← *{r['from_your_words']}*")


with st.sidebar:
    st.write("Backend:", API)
    if st.button("Check health"):
        st.write(api("GET", "/health")[1])
    st.divider()
    st.subheader("Red-team scoreboard")
    if st.button("Run all attacks"):
        code, rt = api("GET", "/demo/redteam")
        if code == 200:
            st.metric("Attacks tried", rt["total"])
            st.metric("Unauthorized ALLOW", rt["unauthorized_allowed"])
            st.write(f"🔴 BLOCK {rt['block']} · 🟡 REVIEW {rt['review']}")
            st.write(f"Control (legit $65 purchase): **{rt['control_legit_purchase']}**")
            with st.expander("Every attack"):
                for r in rt["results"]:
                    st.write(f"{ICON[r['decision']]} `{r['attack']}` → {', '.join(r['reasons'])}")

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
        st.session_state["instruction"] = draft["draft"]["raw_user_request"]
        st.success(f"Mandate {st.session_state['rid']} saved") if code == 200 else st.error(body)

rid = st.session_state.get("rid")
if rid:
    st.header("2. Same agent, same poisoned page")
    scen = api("GET", "/demo/scenarios")[1]
    key = st.selectbox("Scenario", list(scen), format_func=lambda k: f"{k}: {scen[k]}")
    agent_mode = st.radio("Agent", ["scripted", "llm"], horizontal=True,
                          format_func=lambda m: "Scripted (no API key)" if m == "scripted" else "Real LLM (OpenAI)")
    left, right = st.columns(2)
    with left:
        st.subheader("❌ Unprotected")
        if st.button("Run unprotected agent"):
            code, b = api("POST", "/demo/agent", json={"request_id": rid, "scenario": key, "protected": False,
                                                          "agent": agent_mode})
            if code == 200:
                p = b["proposal"]
                st.caption(f"Agent used: {b['agent']}" + (f" ({b['agent_note']})" if b["agent_note"] else ""))
                st.error(f"Order created: {p['quantity']} × {p['product_name']} from {p['merchant_name']} "
                         f"@ {p['unit_price']} {p['currency']}")
                st.json(b["paypal_order"])
            else:
                st.warning(b)
    with right:
        st.subheader("🛡️ Behind TrustPay")
        if st.button("Run protected agent"):
            code, b = api("POST", "/demo/agent", json={"request_id": rid, "scenario": key, "protected": True,
                                                          "agent": agent_mode})
            st.session_state["last"] = b if code == 200 else None
            st.session_state["exec"] = None
    last = st.session_state.get("last")
    if last:
        with right:
            st.caption(f"Agent used: {last.get('agent', 'scripted')}"
                       + (f" ({last['agent_note']})" if last.get("agent_note") else ""))
            st.markdown(f"### {ICON[last['decision']]} {last['decision']}  ·  {', '.join(last['reason_codes']) or 'no issues'}")
            st.write(last["explanation"])
            receipt(last["receipt"], st.session_state.get("instruction", ""))
            pid = last["proposal_id"]
            if last["decision"] == "REVIEW" and st.button("I approve this purchase"):
                code, b = api("POST", f"/transactions/{pid}/approve")
                st.session_state["last"] = b if code == 200 else last
                st.rerun()
            if last.get("decision_token") and st.button("Execute via PayPal"):
                code, b = api("POST", f"/transactions/{pid}/execute", json={"token": last["decision_token"]})
                st.session_state["exec"] = b
            ex = st.session_state.get("exec")
            if ex:
                if ex.get("status") == "PAYER_ACTION_REQUIRED" and ex.get("approve_url"):
                    st.info("Step 2: approve the payment as the sandbox buyer, then come back and finish.")
                    st.link_button("Approve in PayPal sandbox", ex["approve_url"])
                    if st.button("I approved it, finish payment"):
                        code, b = api("POST", f"/transactions/{pid}/execute", json={"token": last["decision_token"]})
                        st.session_state["exec"] = b
                        st.rerun()
                elif ex.get("status") == "COMPLETED":
                    st.success(f"Payment completed. PayPal order {ex['paypal_order_id']}, capture {ex.get('capture_id', '-')}")
                st.json(ex)
                if ex.get("simulated"):
                    st.warning("PayPal is SIMULATED in this run (PAYPAL_SIMULATE=1).")
            if st.checkbox("Audit trail"):
                st.json(api("GET", f"/transactions/{pid}")[1]["audit"])
