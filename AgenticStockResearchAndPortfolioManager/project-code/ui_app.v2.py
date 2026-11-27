"""Streamlit UI: a Chat tab (technical and fundamental questions) and a password-protected Admin tab.

The entry point is app_ui.py. The logic lives here so tests can run it without a browser.
Models are never named here: the Admin tab changes the ROLE settings, and the gateway does the rest.
"""
from __future__ import annotations

import hmac
import html
import json
import os
import threading
import uuid

import streamlit as st

import config
from chat_store import ChatStore, group_label
from model_settings import ROLES, SettingsError, SettingsStore

_CHAT_LOCK = threading.Lock()       # one agent instance is shared, and it keeps per-run state, so run one question at a time
CHAT_SCOPE = ("Ask about Nifty 50 stocks: prices, trend and indicators; financial statements, growth, ratios and "
              "valuation; and what annual reports, transcripts and presentations say. Portfolios are not connected yet.")
EXAMPLES = ["What is the RSI of TCS?", "How has TCS net profit grown over 5 years?",
            "What did TCS management say about attrition and hiring?", "Compare INFY and TCS"]
DISCLAIMER = ("Information from price data, company financial statements, annual reports and earnings-call transcripts "
              "only. Not investment advice. Prices are not adjusted for splits or demergers. Financial values are in "
              "the workbook's units, probably Rs crore.")

# Looks like ChatGPT: a dark sidebar with the history, a centred reading column, a rounded input at the bottom.
STYLE = """
<style>
html, body, [data-testid="stApp"] { background: #ffffff; color: #0d0d0d; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stAppDeployButton"], [data-testid="stToolbar"] { visibility: hidden; }

/* sidebar: pale grey, like ChatGPT */
[data-testid="stSidebar"] { background: #f9f9f9; border-right: 1px solid #ececec; min-width: 300px; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 1rem; }
[data-testid="stSidebar"] .stButton > button {
    width: 100%; justify-content: flex-start; text-align: left; border: 0; background: transparent; color: #0d0d0d;
    border-radius: 10px; padding: 0.5rem 0.75rem; font-size: 0.95rem; font-weight: 400; box-shadow: none; }
[data-testid="stSidebar"] .stButton > button p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
[data-testid="stSidebar"] .stButton > button:hover { background: #ececec; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: #ececec; }
[data-testid="stSidebar"] input { background: #ffffff; border: 1px solid #e3e3e3; border-radius: 10px; }
.brand { font-size: 1.35rem; font-weight: 700; margin: 0 0 0.9rem 0.4rem; letter-spacing: -0.01em; }
.group-label { font-size: 0.82rem; color: #8f8f8f; margin: 1.1rem 0 0.25rem 0.75rem; }

/* conversation: one centred column, user bubble on the right in pale blue */
[data-testid="stMainBlockContainer"] { max-width: 820px; margin: 0 auto; padding-top: 1.2rem; padding-bottom: 7rem; }
[data-testid="stChatMessage"] { background: transparent; padding: 0.7rem 0; gap: 0.9rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse; text-align: left; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    background: #e8f0fe; border-radius: 22px; padding: 0.8rem 1.15rem; max-width: 75%; width: fit-content; }
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] { display: none; }
[data-testid="stChatMessageContent"] p { font-size: 1.02rem; line-height: 1.65; }
[data-testid="stChatMessageContent"] table { border-collapse: collapse; width: 100%; }
[data-testid="stChatMessageContent"] th { text-align: left; border-bottom: 1px solid #e3e3e3; color: #0d0d0d; }
[data-testid="stChatMessageContent"] td { border-bottom: 1px solid #f0f0f0; }
[data-testid="stExpander"] { border: 1px solid #ececec; border-radius: 12px; background: #fafafa; }

/* input: a rounded pill at the bottom */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: #ffffff; }
[data-testid="stBottomBlockContainer"] { max-width: 820px; margin: 0 auto; }
[data-testid="stChatInput"], [data-testid="stChatInput"] > div { border-radius: 28px; background: #ffffff; }
[data-testid="stChatInput"] { border: 1px solid #e3e3e3; box-shadow: 0 2px 10px rgba(0,0,0,0.06); }
[data-testid="stChatInput"] textarea { font-size: 1rem; }

/* empty chat: the welcome line and example cards */
.title-bar { font-size: 1.05rem; font-weight: 600; padding: 0.2rem 0 0.8rem 0; border-bottom: 1px solid #f0f0f0;
    margin-bottom: 1rem; }
.welcome { text-align: center; margin-top: 16vh; font-size: 2rem; font-weight: 600; letter-spacing: -0.01em; }
.scope { text-align: center; color: #6b6b6b; margin: 0.6rem auto 1.8rem auto; max-width: 640px; }
.stButton > button[kind="secondary"] { border-radius: 14px; }
.disclaimer { text-align: center; color: #8f8f8f; font-size: 0.72rem; margin-top: 0.6rem; }
</style>
"""


# ---------------------------------------------------------------------------------------------- shared objects
@st.cache_resource
def get_settings() -> SettingsStore:
    return SettingsStore()


@st.cache_resource
def get_chats() -> ChatStore:
    return ChatStore()


@st.cache_resource
def get_gateway():
    from gateway import Gateway
    return Gateway(settings=get_settings())


@st.cache_resource
def get_agents() -> dict:
    """One agent per route. Each owns its MCP server. Restart the app after code changes."""
    from agent_fundamental import FundamentalAgent
    from agent_technical import TechnicalAgent
    from mcp_client import McpServer
    gateway = get_gateway()
    return {"technical": TechnicalAgent(gateway, McpServer("market-data", "mcp_market_data.py").start()),
            "fundamental": FundamentalAgent(gateway, McpServer("fundamentals", "mcp_fundamentals.py").start())}


def answer(question: str, session: str) -> dict:
    """Route the question and run the agent(s). Returns the history item for the assistant message."""
    from router import route
    chosen = route(question)
    names = ["technical", "fundamental"] if chosen == "both" else ["fundamental" if chosen == "documents" else chosen]
    agents = get_agents()
    parts, trace, budget, stopped = [], [], {}, []
    focus = {"technical": "The question may have two parts. Use your tools for the price, trend and indicator part and "
                          "answer only that. Another agent answers the financial-statement part: do not mention it.",
             "fundamental": "The question may have two parts. Use your tools for the financial-statement, growth, ratio "
                            "and valuation part and answer only that. Another agent answers the price and indicator "
                            "part: do not mention it."}
    for name in names:
        result = agents[name].run(question, session=session, focus=focus[name] if len(names) > 1 else "")
        parts.append(result.answer if len(names) == 1 else f"**{name.capitalize()}**\n\n{result.answer}")
        trace += [{**call, "agent": name} for call in result.tool_trace]
        budget[name] = result.budget
        if result.stopped_early:
            stopped.append(f"{name}: {result.stopped_early}")
    return {"role": "assistant", "text": "\n\n".join(parts), "trace": trace,
            "budget": budget[names[0]] if len(names) == 1 else budget, "stopped": "; ".join(stopped), "route": chosen}


def usage_rows(limit: int = 200) -> list[dict]:
    return get_gateway().usage_rows(limit)


def rag_status() -> dict:
    from rag_store import RagStore
    return RagStore(collection=get_settings().embedding_collection()).status()


# ---------------------------------------------------------------------------------------------- chat
def _open_conversation(cid: str | None) -> None:
    st.session_state["conversation"] = cid
    st.session_state["view"] = "chat"


def render_sidebar() -> None:
    chats = get_chats()
    with st.sidebar:
        st.markdown("<div class='brand'>Agentic Research</div>", unsafe_allow_html=True)
        if st.button("New chat", key="new_chat", icon=":material/edit_square:", on_click=_open_conversation,
                     args=(None,)):
            pass
        search = st.text_input("Search chats", key="chat_search", placeholder="Search chats",
                               label_visibility="collapsed")
        current = st.session_state.get("conversation")
        shown = None
        st.markdown("<div class='group-label'>Recents</div>", unsafe_allow_html=True)
        for conv in chats.list_conversations(query=search):
            label = group_label(conv["updated"])
            if label != shown:
                if shown is not None or label != "Today":
                    st.markdown(f"<div class='group-label'>{label}</div>", unsafe_allow_html=True)
                shown = label
            st.button(conv["title"], key=f"open_{conv['id']}", on_click=_open_conversation, args=(conv["id"],),
                      type="primary" if conv["id"] == current else "secondary")
        if search and shown is None:
            st.caption("No chat matches this search.")
        st.divider()
        st.button("Admin", key="open_admin", icon=":material/settings:",
                  on_click=lambda: st.session_state.update(view="admin"))


def _show_message(item: dict) -> None:
    with st.chat_message(item["role"]):
        st.markdown(item["text"])
        if item.get("trace"):
            with st.expander("Tools used"):
                for call in item["trace"]:
                    prefix = f"[{call['agent']}] " if call.get("agent") else ""
                    st.code(f"{prefix}{call['tool']}({json.dumps(call['arguments'])})", language="text")
                st.caption(f"Route: {item.get('route', '')}. Budget used: {item.get('budget')}")
        if item.get("stopped"):
            st.warning(f"Stopped early: {item['stopped']}")


def _ask(question: str) -> None:
    """Save the question, run the agents, save the answer. Starts a new conversation when none is open."""
    chats = get_chats()
    cid = st.session_state.get("conversation") or chats.new_conversation()
    st.session_state["conversation"] = cid
    chats.add_message(cid, "user", question)
    _show_message({"role": "user", "text": question})
    try:
        with _CHAT_LOCK, st.spinner("Working..."):
            item = answer(question, cid)
    except Exception as exc:                                    # show the problem, do not crash the page
        item = {"role": "assistant", "text": f"I could not answer this: {exc}", "trace": [], "budget": {}}
    chats.add_message(cid, "assistant", item["text"], trace=item.get("trace"), budget=item.get("budget"),
                      route=item.get("route", ""), stopped=item.get("stopped", ""))
    _show_message(item)
    st.rerun()                                      # refresh the sidebar so the new chat appears in the history


def render_chat() -> None:
    chats = get_chats()
    cid = st.session_state.get("conversation")
    history = chats.messages(cid) if cid else []
    clicked = None
    if history:
        title = html.escape(chats.get(cid)["title"])
        st.markdown(f"<div class='title-bar'>{title}</div>", unsafe_allow_html=True)
    if not history:
        st.markdown("<div class='welcome'>What can I help you with?</div>"
                    f"<div class='scope'>{CHAT_SCOPE}</div>", unsafe_allow_html=True)
        columns = st.columns(2)
        for i, example in enumerate(EXAMPLES):
            if columns[i % 2].button(example, key=f"example_{i}"):
                clicked = example
    for item in history:
        _show_message(item)
    question = st.chat_input("Ask about a Nifty 50 stock") or clicked
    st.markdown(f"<div class='disclaimer'>{DISCLAIMER}</div>", unsafe_allow_html=True)
    if question:
        _ask(question)


# ---------------------------------------------------------------------------------------------- admin tab
def _password_ok(entered: str) -> bool:
    expected = os.environ.get("ARPM_ADMIN_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(entered.encode(), expected.encode())


def render_admin() -> None:
    if not os.environ.get("ARPM_ADMIN_PASSWORD"):
        st.warning("The Admin tab is locked because ARPM_ADMIN_PASSWORD is not set. "
                   "Set it in config/arpm.env and restart the app (bin/stop_app.sh, then bin/start_app.sh).")
        return
    if not st.session_state.get("admin_ok"):
        st.text_input("Admin password", type="password", key="admin_pw")
        if st.button("Sign in", key="admin_login"):
            if _password_ok(st.session_state.get("admin_pw", "")):
                st.session_state["admin_ok"] = True
                st.rerun()
            else:
                st.error("The password is incorrect.")
        return

    if st.button("Sign out", key="admin_logout"):
        st.session_state["admin_ok"] = False
        st.rerun()

    store = get_settings()
    models, providers, chunking, usage, rag = st.tabs(["Models", "Providers", "Chunking and RAG", "Usage log", "Change log"])
    with models:
        _models_panel(store)
    with providers:
        _providers_panel(store)
    with chunking:
        _chunking_panel(store)
    with usage:
        _usage_panel()
    with rag:
        _audit_panel(store)


def _models_panel(store: SettingsStore) -> None:
    st.caption("Each role names a provider and a model. Agents ask for a role, so a change here needs no code change.")
    names = [p.name for p in store.list_providers()]
    for role in ROLES:
        cfg = store.get_role(role)
        st.subheader(role)
        c1, c2 = st.columns(2)
        provider = c1.selectbox("Provider", names, index=names.index(cfg.provider), key=f"role_{role}_provider")
        model = c2.text_input("Model", value=cfg.model, key=f"role_{role}_model")
        params_text = st.text_input("Parameters (JSON)", value=json.dumps(cfg.params), key=f"role_{role}_params")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Save", key=f"role_{role}_save"):
            try:
                params = json.loads(params_text or "{}")
                if not isinstance(params, dict):
                    raise ValueError("parameters must be a JSON object, for example {\"temperature\": 0}")
                store.set_role(role, provider, model, params)
                st.success(f"Saved {role}: {provider} / {model}")
                if role == "embedding":
                    st.warning("A new embedding model needs a new document index. Collection name is now "
                               f"{store.embedding_collection()}. Build it with bin/rag_build_bg.sh.")
            except (SettingsError, ValueError) as exc:
                st.error(str(exc))
        if b2.button("Test connection", key=f"role_{role}_test"):
            res = get_gateway().test_connection(role)
            (st.success if res["ok"] else st.error)(f"{'OK' if res['ok'] else 'Failed'}: {res['detail']} ({res['ms']} ms)")


def _providers_panel(store: SettingsStore) -> None:
    st.caption("API keys are read from environment variables. Type the variable NAME here, never the key.")
    for prov in store.list_providers():
        st.subheader(prov.name)
        url = st.text_input("Base URL", value=prov.base_url, key=f"prov_{prov.name}_url",
                            help="Empty means OLLAMA_HOST for a local Ollama.")
        env = st.text_input("API key variable", value=prov.api_key_env, key=f"prov_{prov.name}_env")
        enabled = prov.enabled
        if prov.external:
            enabled = st.checkbox("Enabled (sends prompts and documents off this machine)", value=prov.enabled,
                                  key=f"prov_{prov.name}_on")
        if st.button("Save", key=f"prov_{prov.name}_save"):
            try:
                store.update_provider(prov.name, base_url=url, api_key_env=env, enabled=enabled)
                st.success(f"Saved {prov.name}")
            except SettingsError as exc:
                st.error(str(exc))
        if prov.api_key_env:
            st.caption("Key variable is set." if os.environ.get(prov.api_key_env) else "Key variable is NOT set.")


def _chunking_panel(store: SettingsStore) -> None:
    current = store.get_value("chunking")
    st.subheader("Chunking")
    c1, c2 = st.columns(2)
    size = c1.number_input("Chunk size (characters)", min_value=1, value=int(current["size"]), step=100, key="chunk_size")
    overlap = c2.number_input("Overlap (characters)", min_value=0, value=int(current["overlap"]), step=10, key="chunk_overlap")
    st.caption("Split: by page. A chunk never crosses a page, so every answer can cite a page.")
    if st.button("Save", key="chunk_save"):
        try:
            store.set_value("chunking", {"size": int(size), "overlap": int(overlap), "split": current["split"]})
            st.success(f"Saved. The collection for these settings is {store.embedding_collection()}.")
            st.warning("Existing vectors use the old setting and are kept. Build the new index with "
                       "bin/rag_build_bg.sh, then search switches to it once it is complete.")
        except SettingsError as exc:
            st.error(str(exc))
    st.subheader("Document index")
    try:
        status = rag_status()
        st.write(f"Collection: `{status['collection']}`")
        st.write("Searchable." if status["complete"] else "Not complete, so it is not searched yet.")
        a, b, c, d = st.columns(4)
        a.metric("Files done", status["files_done"])
        b.metric("Stocks", status["stocks"])
        c.metric("Chunks", status["chunks"])
        d.metric("Pages without text", status["empty_pages"])
        if status["files_failed"]:
            st.error(f"{status['files_failed']} file(s) failed. See runtime/logs/rag_build.log.")
    except Exception as exc:
        st.error(f"Could not read the index status: {exc}")


def _usage_panel() -> None:
    rows = usage_rows(200)
    if not rows:
        st.info("No model calls recorded yet.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _audit_panel(store: SettingsStore) -> None:
    rows = store.audit_log(100)
    if not rows:
        st.info("No settings changes recorded yet.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------------------------- page
def render() -> None:
    st.markdown(STYLE, unsafe_allow_html=True)
    st.session_state.setdefault("view", "chat")
    render_sidebar()
    if st.session_state["view"] == "admin":
        st.button("Back to chat", key="back_to_chat", icon=":material/arrow_back:",
                  on_click=lambda: st.session_state.update(view="chat"))
        st.title(config.APP_NAME + " : Admin")
        render_admin()
    else:
        render_chat()
