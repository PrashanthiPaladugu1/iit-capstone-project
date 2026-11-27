"""Gateway, providers and settings: provider switching without code changes, with mocked HTTP."""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gateway import Gateway, GatewayError  # noqa: E402
from model_settings import SettingsError, SettingsStore  # noqa: E402


class Recorder:
    """Fake network. Answers like Ollama, an OpenAI-style API, or Hugging Face, depending on the URL path."""

    def __init__(self):
        self.requests = []
        self.fail_first = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append((request.url.host, request.url.path, body, dict(request.headers)))
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(500, text="boom")
        path = request.url.path
        if path.endswith("/api/chat"):
            return httpx.Response(200, json={
                "message": {"content": "hi from ollama", "tool_calls": [
                    {"function": {"name": "get_ohlcv", "arguments": {"symbol": "TCS"}}}]},
                "prompt_eval_count": 12, "eval_count": 30, "total_duration": 2_000_000_000,
                "load_duration": 500_000_000, "eval_duration": 1_000_000_000})
        if path.endswith("/api/embed"):
            return httpx.Response(200, json={"embeddings": [[0.1] * 768 for _ in body["input"]],
                                             "prompt_eval_count": 5, "total_duration": 1_000_000})
        if path.endswith("chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi from api"}}],
                                             "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
        if path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.2] * 1024}
                                                      for i, _ in enumerate(body["input"])],
                                             "usage": {"prompt_tokens": 9}})
        if "feature-extraction" in path:
            return httpx.Response(200, json=[[0.3] * 384 for _ in body["inputs"]])
        return httpx.Response(404, text="nope")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.test:11434")
    monkeypatch.setenv("HF_TOKEN", "hf_secret_123")
    monkeypatch.setenv("EXTERNAL_API_KEY", "ext_secret_456")
    store = SettingsStore(tmp_path / "settings.sqlite")
    fake = Recorder()
    gw = Gateway(store, tmp_path / "usage.sqlite", transport=httpx.MockTransport(fake), retries=1)
    return store, gw, fake


MSG = [{"role": "user", "content": "price of TCS?"}]


def test_default_is_local_ollama_with_tools_and_exact_tokens(env):
    store, gw, fake = env
    res = gw.chat("chat", MSG, agent="agent_technical", session="s1", preview="price of TCS?")
    assert res.text == "hi from ollama" and res.provider == "ollama_local" and res.model == "gemma4:12b"
    assert res.tool_calls[0]["name"] == "get_ohlcv" and res.tool_calls[0]["arguments"] == {"symbol": "TCS"}
    assert (res.tokens_in, res.tokens_out, res.tokens_estimated) == (12, 30, False)
    row = gw.usage_rows(1)[0]
    assert row["tokens_per_s"] == 30.0 and row["external"] == 0 and row["agent"] == "agent_technical"
    assert fake.requests[0][0] == "ollama.test"


def test_default_models_per_role_and_chat_skips_the_thinking_phase(env):
    """chat is gemma4:12b because mistral:7b never called the tools in live tests (19 Nov 2026)."""
    store, gw, fake = env
    roles = {r.role: (r.provider, r.model) for r in store.list_roles()}
    assert roles["chat"] == ("ollama_local", "gemma4:12b")
    assert roles["router"] == ("ollama_local", "mistral:7b")
    assert roles["embedding"] == ("ollama_local", "nomic-embed-text")
    assert store.get_role("chat").params == {"think": False}
    gw.chat("chat", MSG)
    body = fake.requests[0][2]
    assert body["model"] == "gemma4:12b" and body["think"] is False


def test_switch_chat_to_external_api_needs_opt_in_then_works_without_code_change(env):
    store, gw, fake = env
    with pytest.raises(SettingsError, match="not enabled"):
        store.set_role("chat", "external_api", "some-model")
    store.update_provider("external_api", base_url="https://api.example.test/v1", enabled=True)
    store.set_role("chat", "external_api", "some-model")
    res = gw.chat("chat", MSG)                                 # same call as before
    assert res.text == "hi from api" and res.provider == "external_api" and res.model == "some-model"
    host, path, body, headers = fake.requests[-1]
    assert host == "api.example.test" and path == "/v1/chat/completions"
    assert headers["authorization"] == "Bearer ext_secret_456"
    assert gw.usage_rows(1)[0]["external"] == 1


def test_switch_embedding_to_huggingface_and_back(env):
    store, gw, fake = env
    assert gw.embed(["a", "b"]).dims == 768
    store.update_provider("huggingface", enabled=True)
    store.set_role("embedding", "huggingface", "BAAI/bge-small-en-v1.5")
    res = gw.embed(["a", "b"])
    assert res.dims == 384 and res.provider == "huggingface" and res.tokens_estimated
    assert "feature-extraction" in fake.requests[-1][1]
    store.set_role("embedding", "ollama_local", "nomic-embed-text")
    assert gw.embed(["a"]).dims == 768


def test_external_provider_cannot_be_used_when_disabled_even_if_saved(env):
    store, gw, _ = env
    store.update_provider("external_api", base_url="https://api.example.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m")
    store.update_provider("external_api", enabled=False)       # opt-in withdrawn
    with pytest.raises(GatewayError, match="not enabled"):
        gw.chat("chat", MSG)


def test_missing_api_key_is_a_clear_error_and_is_not_retried(env, monkeypatch):
    store, gw, fake = env
    store.update_provider("external_api", base_url="https://api.example.test/v1", enabled=True)
    store.set_role("judge", "external_api", "m")
    monkeypatch.delenv("EXTERNAL_API_KEY")
    with pytest.raises(GatewayError, match="EXTERNAL_API_KEY"):
        gw.chat("judge", MSG)
    assert fake.requests == []
    assert gw.usage_rows(1)[0]["status"] == "error" and gw.usage_rows(1)[0]["attempts"] == 1


def test_retry_once_then_success_and_then_failure_logged(env):
    store, gw, fake = env
    fake.fail_first = 1
    assert gw.chat("chat", MSG).text == "hi from ollama"
    assert gw.usage_rows(1)[0]["attempts"] == 2
    fake.fail_first = 5
    with pytest.raises(GatewayError):
        gw.chat("chat", MSG)
    row = gw.usage_rows(1)[0]
    assert row["status"] == "error" and "HTTP 500" in row["error"]


def test_key_never_appears_in_log_or_error(env):
    store, gw, fake = env
    store.update_provider("external_api", base_url="https://api.example.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m")
    fake.fail_first = 5
    with pytest.raises(GatewayError) as err:
        gw.chat("chat", MSG)
    assert "ext_secret_456" not in str(err.value)
    assert "ext_secret_456" not in json.dumps(gw.usage_rows(5))
    assert "ext_secret_456" not in json.dumps(store.audit_log())


def test_settings_validation_and_audit(env):
    store, gw, _ = env
    with pytest.raises(SettingsError):
        store.update_provider("huggingface", api_key_env="hf_real_key_value")      # a key, not a name
    with pytest.raises(SettingsError):
        store.set_role("nope", "ollama_local", "m")
    with pytest.raises(SettingsError):
        store.set_role("chat", "ollama_local", " ")
    with pytest.raises(SettingsError):
        store.set_value("chunking", {"size": 50, "overlap": 0, "split": "page"})
    store.set_role("judge", "ollama_local", "gemma4:e4b", actor="sangram")
    last = store.audit_log(1)[0]
    assert last["actor"] == "sangram" and last["item"] == "role:judge"
    assert json.loads(last["old"])["model"] == "gemma4:12b" and json.loads(last["new"])["model"] == "gemma4:e4b"


def test_collection_name_changes_with_embedding_model_and_chunking(env):
    store, _, _ = env
    a = store.embedding_collection()
    store.set_value("chunking", {"size": 800, "overlap": 100, "split": "page"})
    b = store.embedding_collection()
    store.update_provider("huggingface", enabled=True)
    store.set_role("embedding", "huggingface", "BAAI/bge-small-en-v1.5")
    c = store.embedding_collection()
    assert len({a, b, c}) == 3 and all(len(x) >= 3 for x in (a, b, c))


def test_test_connection_reports_without_raising_and_is_not_logged(env):
    store, gw, _ = env
    assert gw.test_connection("chat")["ok"] is True
    assert gw.test_connection("embedding")["detail"] == "768 dimensions"
    assert gw.usage_rows() == []
    store.update_provider("external_api", base_url="https://api.example.test/v1", enabled=True)
    store.set_role("chat", "external_api", "m")
    store.update_provider("external_api", enabled=False)
    assert gw.test_connection("chat")["ok"] is False


def test_settings_survive_new_store_instance(env, tmp_path):
    store, _, _ = env
    store.set_role("router", "ollama_local", "llama3.2:1b")
    assert SettingsStore(tmp_path / "settings.sqlite").get_role("router").model == "llama3.2:1b"
