"""AI gateway: the single entry point for every model call in the app.

    gw = Gateway()
    gw.chat("chat", messages, tools=tools, agent="agent_technical", session=sid)
    gw.embed(texts)                       # role "embedding"

Callers name a ROLE, never a provider or model. The gateway reads the saved settings (model_settings.py) on
every call, picks the adapter (providers.py: local Ollama, Hugging Face, external OpenAI-compatible API),
retries once, times and counts the call, and writes one row to the usage log. Switching provider, for
example from Ollama on the Mac to Hugging Face on EC2, is a settings change and needs no code change.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import httpx

import config
from model_settings import SettingsError, SettingsStore
from providers import BaseProvider, ChatResult, EmbedResult, ProviderError, build_provider

PREVIEW_CHARS = 80

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, parent_id INTEGER,
    session TEXT, agent TEXT, node TEXT, route TEXT, role TEXT NOT NULL, kind TEXT NOT NULL,
    provider TEXT, provider_kind TEXT, external INTEGER, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, tokens_estimated INTEGER,
    total_ms REAL, load_ms REAL, eval_ms REAL, tokens_per_s REAL,
    status TEXT NOT NULL, error TEXT, attempts INTEGER, preview TEXT);
CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts);
"""


class GatewayError(RuntimeError):
    pass


class Gateway:
    def __init__(self, settings: SettingsStore | None = None, usage_db: Path | str | None = None,
                 transport: httpx.BaseTransport | None = None, retries: int = 1):
        self.settings = settings or SettingsStore()
        self.usage_db = Path(usage_db) if usage_db else config.usage_db()
        self.usage_db.parent.mkdir(parents=True, exist_ok=True)
        self._transport = transport          # tests inject httpx.MockTransport
        self._retries = retries
        self._providers: dict[tuple, BaseProvider] = {}
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)

    # ------------------------------------------------------------------ public API
    def chat(self, role: str, messages: list[dict], tools: list[dict] | None = None, *,
             params: dict | None = None, session: str = "", agent: str = "", node: str = "", route: str = "",
             parent_call_id: int | None = None, preview: str = "") -> ChatResult:
        cfg, prov = self._resolve(role)
        merged = {**cfg.params, **(params or {})}
        result, call_id = self._run(
            role, "chat", cfg, prov, parent_call_id, session, agent, node, route, preview,
            lambda p: p.chat(cfg.model, messages, tools, merged))
        result.provider, result.model, result.call_id = cfg.provider, cfg.model, call_id
        return result

    def embed(self, texts: list[str], *, role: str = "embedding", session: str = "", agent: str = "",
              node: str = "", parent_call_id: int | None = None) -> EmbedResult:
        cfg, prov = self._resolve(role)
        result, call_id = self._run(
            role, "embed", cfg, prov, parent_call_id, session, agent, node, "", "",
            lambda p: p.embed(cfg.model, texts))
        result.provider, result.model, result.call_id = cfg.provider, cfg.model, call_id
        return result

    def test_connection(self, role: str) -> dict:
        """One small call with the role's current settings. Used by the Admin tab before saving a change.
        Not written to the usage log."""
        try:
            cfg, prov = self._resolve(role)
            adapter = self._adapter(prov)
            if role == "embedding":
                res = adapter.embed(cfg.model, ["connection test"])
                return {"ok": bool(res.vectors), "detail": f"{res.dims} dimensions", "ms": round(res.total_ms)}
            res = adapter.chat(cfg.model, [{"role": "user", "content": "Reply with the word OK."}],
                               None, {**cfg.params, "max_tokens": 8})
            return {"ok": True, "detail": (res.text or "").strip()[:40], "ms": round(res.total_ms)}
        except (ProviderError, SettingsError, GatewayError) as exc:
            return {"ok": False, "detail": str(exc)[:200], "ms": 0}

    # ------------------------------------------------------------------ internals
    def _resolve(self, role: str):
        cfg = self.settings.get_role(role)
        prov = self.settings.get_provider(cfg.provider)
        if prov.external and not prov.enabled:
            raise GatewayError(f"provider '{prov.name}' is external and not enabled (role '{role}')")
        return cfg, prov

    def _adapter(self, prov) -> BaseProvider:
        key = prov.api_key()
        cache_key = (prov.kind, prov.resolved_base_url(), key)
        adapter = self._providers.get(cache_key)
        if adapter is None:
            if prov.api_key_env and not key:
                raise GatewayError(f"environment variable {prov.api_key_env} is not set (provider '{prov.name}')")
            adapter = build_provider(prov.kind, prov.resolved_base_url(), key,
                                     timeout=config.CALL_TIMEOUT_S, transport=self._transport)
            self._providers[cache_key] = adapter
        return adapter

    def _run(self, role, kind, cfg, prov, parent_id, session, agent, node, route, preview, fn):
        started = time.time()
        attempts, last_error = 0, ""
        for attempt in range(self._retries + 1):
            attempts = attempt + 1
            try:
                result = fn(self._adapter(prov))
                call_id = self._log(started, parent_id, session, agent, node, route, role, kind, cfg, prov,
                                    result, "ok", "", attempts, preview)
                return result, call_id
            except ProviderError as exc:
                last_error = self._clean(str(exc), prov)
            except GatewayError as exc:
                last_error = str(exc)
                break                                                   # a missing key will not fix itself
        self._log(started, parent_id, session, agent, node, route, role, kind, cfg, prov,
                  None, "error", last_error, attempts, preview)
        raise GatewayError(f"{role}: {last_error}")

    @staticmethod
    def _clean(message: str, prov) -> str:
        key = prov.api_key()
        return message.replace(key, "***") if key else message

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.usage_db, timeout=10)

    def _log(self, started, parent_id, session, agent, node, route, role, kind, cfg, prov, result, status, error,
             attempts, preview) -> int:
        tokens_in = getattr(result, "tokens_in", 0)
        tokens_out = getattr(result, "tokens_out", 0)
        total_ms = getattr(result, "total_ms", 0.0) or (time.time() - started) * 1000
        eval_ms = getattr(result, "eval_ms", 0.0)
        speed = round(tokens_out / (eval_ms / 1000), 2) if eval_ms else (
            round(tokens_out / (total_ms / 1000), 2) if tokens_out and total_ms else 0.0)
        row = (started, parent_id, session, agent, node, route, role, kind, prov.name, prov.kind, int(prov.external),
               cfg.model, tokens_in, tokens_out, int(getattr(result, "tokens_estimated", False)), total_ms,
               getattr(result, "load_ms", 0.0), eval_ms, speed, status, error, attempts, (preview or "")[:PREVIEW_CHARS])
        with closing(self._connect()) as con, con:
            cur = con.execute(
                "INSERT INTO calls(ts,parent_id,session,agent,node,route,role,kind,provider,provider_kind,external,model,"
                "tokens_in,tokens_out,tokens_estimated,total_ms,load_ms,eval_ms,tokens_per_s,status,error,attempts,preview)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            return int(cur.lastrowid)

    def usage_rows(self, limit: int = 200) -> list[dict]:
        with closing(self._connect()) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM calls ORDER BY id DESC LIMIT ?", (limit,))]
