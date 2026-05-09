
"""
Simple Streamlit auth for V3.

This is basic app-level protection, not enterprise SSO.
Use env vars:
- FCCT_AUTH_ENABLED=true
- FCCT_USERNAME=admin
- FCCT_PASSWORD=change-me
"""

from __future__ import annotations

import hmac
import os
import streamlit as st


def auth_enabled() -> bool:
    return os.getenv("FCCT_AUTH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def require_login() -> None:
    if not auth_enabled():
        return

    expected_user = os.getenv("FCCT_USERNAME", "admin")
    expected_pass = os.getenv("FCCT_PASSWORD", "change-me")

    if st.session_state.get("authenticated"):
        return

    st.title("FCCT GPU Cascade Guard")
    st.subheader("Login required")

    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        ok_user = hmac.compare_digest(username, expected_user)
        ok_pass = hmac.compare_digest(password, expected_pass)
        if ok_user and ok_pass:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid credentials.")

    st.stop()
