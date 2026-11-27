"""Model settings: which provider and model each role uses. Stored in SQLite and read on every gateway call,
so a change made in the Admin tab applies to the next call with no restart and no code change.

Roles:  chat (agents, synthesizer), router, embedding, summary, judge.
Other settings (plain key/value): chunking, retrieval.
API keys are NEVER stored here. A provider holds only the NAME of the environment variable that has the key.
Every change is written to the audit table.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import config

ROLES = ("chat", "router", "embedding", "summary", "judge", "sentiment")

DEFAULT_PROVIDERS = {
    # name: (kind, base_url, api_key_env, external, enabled)
    "ollama_local": ("ollama", "", "", False, True),                                  # empty URL: use OLLAMA_HOST
    "huggingface": ("huggingface", "https://router.huggingface.co", "HF_TOKEN", True, False),
    "external_api": ("openai_compat", "", "EXTERNAL_API_KEY", True, False),           # for example the course-provided API
}

DEFAULT_ROLES = {
    # chat needs reliable tool calling: gemma4:12b did it in live tests, mistral:7b did not (19 Nov 2026).
    "chat": ("ollama_local", "gemma4:12b", {"think": False}),
    "router": ("ollama_local", "mistral:7b", {"temperature": 0}),
    "embedding": ("ollama_local", "nomic-embed-text", {}),
    "summary": ("ollama_local", "mistral:7b", {}),
    "judge": ("ollama_local", "gemma4:12b", {"think": False, "temperature": 0}),
    # Labels news headlines positive, negative or neutral. Same model as chat, so no extra model is loaded (checked 26 Nov 2026:
    # 12 headlines in 8.5 s; gemma4:12b, mistral:7b and phi4-mini agreed on 9 to 10 of 12).
    "sentiment": ("ollama_local", "gemma4:12b", {"think": False, "temperature": 0}),
}

DEFAULT_VALUES = {
    "chunking": {"size": 1000, "overlap": 150, "split": "page"},     # split: page | section
    "retrieval": {"top_k": 8, "reranker": None},
    "cost_cap": {"daily": None},                                       # money per day for paid providers; None = no cap
    "agents": {"parallel": False},                                     # research analyst runs technical + fundamental at once
    "guardrails": {"custom": [], "next": 1},                           # custom keyword and prompt rules (see guardrail_rules.py)
}
EVENT_ACTIONS = ("block", "warn")


class SettingsError(ValueError):
    pass


@dataclass
class ProviderConfig:
    name: str
    kind: str
    base_url: str
    api_key_env: str
    external: bool
    enabled: bool

    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        if self.kind == "ollama":
            host = os.environ.get("OLLAMA_HOST", "")
            if not host:
                raise SettingsError("OLLAMA_HOST is not set. Set it in config/arpm.env or give the provider a base URL "
                                    "in the Admin tab.")
            return host
        return ""

    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""


@dataclass
class RoleConfig:
    role: str
    provider: str
    model: str
    params: dict = field(default_factory=dict)


class SettingsStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else config.settings_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with closing(self._connect()) as con, con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS providers(
                    name TEXT PRIMARY KEY, kind TEXT NOT NULL, base_url TEXT NOT NULL DEFAULT '',
                    api_key_env TEXT NOT NULL DEFAULT '', external INTEGER NOT NULL, enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS roles(
                    role TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rates(
                    provider TEXT NOT NULL, model TEXT NOT NULL, per_m_in REAL NOT NULL, per_m_out REAL NOT NULL,
                    PRIMARY KEY(provider, model));
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
                    item TEXT NOT NULL, old TEXT, new TEXT);
                CREATE TABLE IF NOT EXISTS guardrail_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, rule_id TEXT NOT NULL, action TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', session TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '');
            """)
            for name, (kind, url, env, external, enabled) in DEFAULT_PROVIDERS.items():
                con.execute("INSERT OR IGNORE INTO providers VALUES(?,?,?,?,?,?)",
                            (name, kind, url, env, int(external), int(enabled)))
            for role, (prov, model, params) in DEFAULT_ROLES.items():
                con.execute("INSERT OR IGNORE INTO roles VALUES(?,?,?,?)", (role, prov, model, json.dumps(params)))
            for key, value in DEFAULT_VALUES.items():
                con.execute("INSERT OR IGNORE INTO kv VALUES(?,?)", (key, json.dumps(value)))

    # ------------------------------------------------------------------ audit
    def _audit(self, con: sqlite3.Connection, actor: str, item: str, old, new) -> None:
        con.execute("INSERT INTO audit(ts, actor, item, old, new) VALUES(?,?,?,?,?)",
                    (time.time(), actor, item, json.dumps(old), json.dumps(new)))

    def audit_log(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ providers
    def get_provider(self, name: str) -> ProviderConfig:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM providers WHERE name=?", (name,)).fetchone()
        if row is None:
            raise SettingsError(f"unknown provider: {name}")
        return ProviderConfig(row["name"], row["kind"], row["base_url"], row["api_key_env"],
                              bool(row["external"]), bool(row["enabled"]))

    def list_providers(self) -> list[ProviderConfig]:
        with closing(self._connect()) as con:
            names = [r["name"] for r in con.execute("SELECT name FROM providers ORDER BY name")]
        return [self.get_provider(n) for n in names]

    def update_provider(self, name: str, *, base_url: str | None = None, api_key_env: str | None = None,
                        enabled: bool | None = None, actor: str = "admin") -> ProviderConfig:
        """Change a provider's URL, key variable name or opt-in. Enabling an external provider is the explicit opt-in."""
        if api_key_env is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]*", api_key_env or "A"):
            raise SettingsError("api_key_env must be an environment variable NAME such as HF_TOKEN, not the key itself")
        old = self.get_provider(name)
        new = ProviderConfig(name, old.kind, old.base_url if base_url is None else base_url,
                             old.api_key_env if api_key_env is None else api_key_env,
                             old.external, old.enabled if enabled is None else enabled)
        with closing(self._connect()) as con, con:
            con.execute("UPDATE providers SET base_url=?, api_key_env=?, enabled=? WHERE name=?",
                        (new.base_url, new.api_key_env, int(new.enabled), name))
            self._audit(con, actor, f"provider:{name}",
                        {"base_url": old.base_url, "api_key_env": old.api_key_env, "enabled": old.enabled},
                        {"base_url": new.base_url, "api_key_env": new.api_key_env, "enabled": new.enabled})
        return new

    # ------------------------------------------------------------------ roles
    def get_role(self, role: str) -> RoleConfig:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM roles WHERE role=?", (role,)).fetchone()
        if row is None:
            raise SettingsError(f"unknown role: {role}")
        return RoleConfig(row["role"], row["provider"], row["model"], json.loads(row["params"]))

    def list_roles(self) -> list[RoleConfig]:
        return [self.get_role(r) for r in ROLES]

    def set_role(self, role: str, provider: str, model: str, params: dict | None = None,
                 actor: str = "admin") -> RoleConfig:
        if role not in ROLES:
            raise SettingsError(f"unknown role: {role}")
        if not model or not model.strip():
            raise SettingsError("model name is empty")
        prov = self.get_provider(provider)
        if prov.external and not prov.enabled:
            raise SettingsError(f"provider '{provider}' sends data off this machine and is not enabled. "
                                f"Enable it first (explicit opt-in).")
        old = self.get_role(role)
        new = RoleConfig(role, provider, model.strip(), old.params if params is None else params)
        with closing(self._connect()) as con, con:
            con.execute("UPDATE roles SET provider=?, model=?, params=? WHERE role=?",
                        (new.provider, new.model, json.dumps(new.params), role))
            self._audit(con, actor, f"role:{role}",
                        {"provider": old.provider, "model": old.model, "params": old.params},
                        {"provider": new.provider, "model": new.model, "params": new.params})
        return new

    # ------------------------------------------------------------------ chunking, retrieval
    def get_value(self, key: str) -> dict:
        with closing(self._connect()) as con:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            raise SettingsError(f"unknown setting: {key}")
        return json.loads(row["value"])

    def set_value(self, key: str, value: dict, actor: str = "admin") -> dict:
        if key not in DEFAULT_VALUES:
            raise SettingsError(f"unknown setting: {key}")
        if key == "chunking":
            size, overlap = value.get("size"), value.get("overlap")
            if not (isinstance(size, int) and 200 <= size <= 8000):
                raise SettingsError("chunk size must be a whole number from 200 to 8000 characters")
            if not (isinstance(overlap, int) and 0 <= overlap < size // 2):
                raise SettingsError("overlap must be a whole number from 0 to less than half the chunk size")
            if value.get("split") not in ("page", "section"):
                raise SettingsError("split must be 'page' or 'section'")
        if key == "retrieval":
            top_k = value.get("top_k")
            if not (isinstance(top_k, int) and 1 <= top_k <= 50):
                raise SettingsError("top_k must be a whole number from 1 to 50")
        if key == "agents":
            if set(value) != {"parallel"} or not isinstance(value["parallel"], bool):
                raise SettingsError("agents setting must be {\"parallel\": true or false}")
        if key == "guardrails":
            from guardrail_rules import validate          # imported here: guardrail_rules imports SettingsError from this file
            validate(value)
        if key == "cost_cap":
            daily = value.get("daily")
            if daily is not None and not (isinstance(daily, (int, float)) and not isinstance(daily, bool) and daily >= 0):
                raise SettingsError("daily cost cap must be a number of 0 or more, or empty for no cap")
        old = self.get_value(key)
        with closing(self._connect()) as con, con:
            con.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(value), key))
            self._audit(con, actor, f"value:{key}", old, value)
        return value

    # ------------------------------------------------------------------ guardrail events
    def log_guardrail_event(self, rule_id: str, action: str, summary: str, session: str = "", route: str = "") -> None:
        """One row each time a custom guardrail fires. Only the first characters of the question are kept."""
        from guardrail_rules import SUMMARY_CHARS
        if action not in EVENT_ACTIONS:
            raise SettingsError(f"guardrail event action must be one of {EVENT_ACTIONS}")
        with closing(self._connect()) as con, con:
            con.execute("INSERT INTO guardrail_events(ts, rule_id, action, summary, session, route) VALUES(?,?,?,?,?,?)",
                        (time.time(), rule_id, action, " ".join((summary or "").split())[:SUMMARY_CHARS], session or "", route or ""))

    def guardrail_events(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM guardrail_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def guardrail_stats(self) -> dict[str, dict]:
        """{rule_id: {"count": n, "last_ts": seconds}} for every rule that has fired at least once."""
        with closing(self._connect()) as con:
            rows = con.execute("SELECT rule_id, COUNT(*) AS n, MAX(ts) AS last FROM guardrail_events GROUP BY rule_id").fetchall()
        return {r["rule_id"]: {"count": r["n"], "last_ts": r["last"]} for r in rows}

    # ------------------------------------------------------------------ rates (price per 1M tokens)
    def get_rate(self, provider: str, model: str) -> tuple[float, float] | None:
        """(per 1M input tokens, per 1M output tokens), or None when no rate is set. A local provider with no rate
        set is free. An external provider with no rate is UNKNOWN: a price is never invented."""
        with closing(self._connect()) as con:
            row = con.execute("SELECT per_m_in, per_m_out FROM rates WHERE provider=? AND model=?",
                              (provider, model)).fetchone()
        if row is not None:
            return float(row["per_m_in"]), float(row["per_m_out"])
        try:
            external = self.get_provider(provider).external
        except SettingsError:
            return None
        return None if external else (0.0, 0.0)

    def set_rate(self, provider: str, model: str, per_m_in, per_m_out, actor: str = "admin") -> None:
        for value in (per_m_in, per_m_out):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise SettingsError("a rate must be a number of 0 or more (price per 1 million tokens)")
        if not model or not model.strip():
            raise SettingsError("model name is empty")
        self.get_provider(provider)
        old = self.get_rate(provider, model.strip())
        with closing(self._connect()) as con, con:
            con.execute("INSERT INTO rates VALUES(?,?,?,?) ON CONFLICT(provider, model) DO UPDATE SET "
                        "per_m_in=excluded.per_m_in, per_m_out=excluded.per_m_out",
                        (provider, model.strip(), float(per_m_in), float(per_m_out)))
            self._audit(con, actor, f"rate:{provider}:{model.strip()}", old, [float(per_m_in), float(per_m_out)])

    def list_rates(self) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM rates ORDER BY provider, model").fetchall()
        return [{"provider": r["provider"], "model": r["model"], "per_m_in": r["per_m_in"], "per_m_out": r["per_m_out"]}
                for r in rows]

    # ------------------------------------------------------------------ vector collection identity
    def embedding_collection(self, chunking: dict | None = None) -> str:
        """Name of the vector collection for the CURRENT embedding model and chunking.
        Changing either gives a new name, so old vectors are never mixed with new ones (re-index needed).
        `chunking` lets the rebuild script name a collection for values given on its command line."""
        role = self.get_role("embedding")
        chunk = chunking or self.get_value("chunking")
        raw = f"{role.provider}-{role.model}-{chunk['split']}-c{chunk['size']}-o{chunk['overlap']}"
        return re.sub(r"[^A-Za-z0-9._-]", "_", raw)
