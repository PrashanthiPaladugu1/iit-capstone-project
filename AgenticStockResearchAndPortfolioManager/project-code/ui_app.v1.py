"""Streamlit UI: a Chat tab (technical and fundamental questions) and a password-protected Admin tab.

The entry point is app_ui.py. The logic lives here so tests can run it without a browser.
Models are never named here: the Admin tab changes the ROLE settings, and the gateway does the rest.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import uuid

import streamlit as st

import config
from model_settings import ROLES, SettingsError, SettingsStore

_CHAT_LOCK = threading.Lock()       # one agent instance is shared, and it keeps per-run state, so run one question at a time
CHAT_SCOPE = ("This chat answers technical questions (prices, trend, RSI, MACD, volatility, movers) and fundamental "
              "questions (financial statements, growth, ratios, valuation, and what annual reports, transcripts and "
              "presentations say) about Nifty 50 stocks. Portfolios are not connected yet.")
EXAMPLES = ["What is the RSI of TCS?", "How has TCS net profit grown over 5 years?",
            "Compare ROE of INFY and TCS.", "Top 5 movers on the last day."]


# ---------------------------------------------------------------------------------------------- shared objects
@st.cache_resource
def get_settings() -> SettingsStore:
    return SettingsStore()


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


# ---------------------------------------------------------------------------------------------- chat tab
def render_chat() -> None:
    st.info(CHAT_SCOPE)
    st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
    history = st.session_state.setdefault("history", [])

    question = st.chat_input("Ask about a Nifty 50 stock: price and indicators, or financial statements and ratios")
    if question:
        history.append({"role": "user", "text": question})
        try:
            with _CHAT_LOCK, st.spinner("Working..."):
                history.append(answer(question, st.session_state["session_id"]))
        except Exception as exc:                                    # show the problem, do not crash the page
            history.append({"role": "assistant", "text": f"I could not answer this: {exc}", "trace": [], "budget": {}})

    if not history:
        st.caption("Examples: " + "  |  ".join(EXAMPLES))
    for item in history:
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
    st.caption("Information from price data, company financial statements, annual reports and earnings-call "
               "transcripts only. Not investment advice. Prices are not adjusted for splits or demergers. "
               "Financial values are in the workbook's units, probably Rs crore.")


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
    st.title(config.APP_NAME)
    chat_tab, admin_tab = st.tabs(["Chat", "Admin"])
    with chat_tab:
        render_chat()
    with admin_tab:
        render_admin()
