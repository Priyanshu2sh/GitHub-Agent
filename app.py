"""
Streamlit chat UI for the GitHub PR assistant.

Run with:
    streamlit run app.py
"""

import asyncio
import streamlit as st

from agent import GitHubChatAgent

st.set_page_config(page_title="GitHub PR Assistant", page_icon="🐙", layout="centered")
st.title("🐙 GitHub PR Assistant")
st.caption(
    "Ask about your repos or open PRs, or ask me to comment on a PR — all in chat. "
    "Scoped to repositories you personally own."
)


def get_event_loop() -> asyncio.AbstractEventLoop:
    """One persistent event loop per browser session, so the MCP subprocess
    connection stays alive across Streamlit's rerun-per-interaction model."""
    if "event_loop" not in st.session_state:
        st.session_state.event_loop = asyncio.new_event_loop()
    return st.session_state.event_loop


def get_agent() -> GitHubChatAgent:
    """Create the agent once per session and connect it to the MCP server."""
    if "agent" not in st.session_state:
        loop = get_event_loop()
        agent = GitHubChatAgent()
        with st.spinner("Connecting to GitHub..."):
            loop.run_until_complete(agent.start())
        st.session_state.agent = agent
    return st.session_state.agent


if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.subheader("Session")
    if st.button("Reset conversation"):
        for key in ("agent", "event_loop", "messages"):
            st.session_state.pop(key, None)
        st.rerun()
    st.caption("Resetting reconnects to GitHub and clears chat history.")

try:
    agent = get_agent()
    loop = get_event_loop()
except Exception as e:
    st.error(f"Failed to start the agent: {e}")
    st.stop()

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("e.g. show all open prs")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Working on it..."):
            try:
                reply = loop.run_until_complete(agent.chat(user_input))
            except Exception as e:
                reply = f"Something went wrong: {e}"
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})