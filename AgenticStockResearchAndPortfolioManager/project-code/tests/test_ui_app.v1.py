import ui_app
from model_settings import SettingsStore
from streamlit.testing.v1 import AppTest


def run_app():
    import ui_app as u
    u.render()


class FakeResult:
    answer = "TCS RSI is 55."
    tool_trace = [{"tool": "get_indicators", "arguments": {"symbol": "TCS"}}]
    budget = {"model_calls": 2, "tool_calls": 1, "tokens": 300, "depth": 1}
    stopped_early = ""


class FakeAgent:
    def __init__(self, text="TCS RSI is 55."):
        self.questions = []
        self.focus = []
        self.text = text

    def run(self, question, focus="", **kw):
        self.questions.append(question)
        self.focus.append(focus)
        result = FakeResult()
        result.answer = self.text
        return result


def make(monkeypatch, tmp_path, password="secret"):
    monkeypatch.setenv("ARPM_ADMIN_PASSWORD", password)
    store = SettingsStore(tmp_path / "s.sqlite")
    agent = FakeAgent()
    fundamental = FakeAgent("TCS net profit grew 8.7% a year.")
    agent.fundamental = fundamental                      # the tests read it back through the technical fake
    monkeypatch.setattr(ui_app, "get_settings", lambda: store)
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": fundamental})
    monkeypatch.setattr(ui_app, "get_gateway", lambda: None)
    monkeypatch.setattr(ui_app, "usage_rows", lambda limit=200: [])
    monkeypatch.setattr(ui_app, "rag_status", lambda: {"collection": "c", "complete": False, "files_done": 0,
                                                       "files_failed": 0, "stocks": 0, "pages": 0, "empty_pages": 0,
                                                       "chunks": 0})
    at = AppTest.from_function(run_app, default_timeout=20)
    return at, store, agent


def test_chat_answers_technical_question_and_states_its_scope(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert any("technical" in c.value.lower() and "fundamental" in c.value.lower() for c in list(at.info))
    at.chat_input[0].set_value("RSI of TCS?").run()
    assert agent.questions == ["RSI of TCS?"] and agent.fundamental.questions == []
    assert agent.focus == [""]                                                 # single route: no split instruction
    assert any("TCS RSI is 55." in m.value for m in at.markdown)


def test_financial_statement_question_goes_to_the_fundamental_agent(monkeypatch, tmp_path):
    """The user's real question: 'check financial statement of infosys' was answered by the technical agent."""
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("check financial statement of infosys").run()
    assert not at.exception
    assert agent.questions == [] and agent.fundamental.questions == ["check financial statement of infosys"]
    assert any("net profit grew" in m.value for m in at.markdown)


def test_mixed_question_runs_both_agents_and_labels_each_answer(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("Revenue growth and RSI of INFY").run()
    assert agent.questions and agent.fundamental.questions
    text = " ".join(m.value for m in at.markdown)
    assert "Technical" in text and "Fundamental" in text and "TCS RSI is 55." in text and "net profit grew" in text
    assert agent.questions == agent.fundamental.questions == ["Revenue growth and RSI of INFY"]   # same question
    assert "price, trend and indicator part" in agent.focus[0]                 # each agent is told its own half
    assert "financial-statement, growth" in agent.fundamental.focus[0]


def test_document_question_goes_to_the_fundamental_agent(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    q = "10 good points from last 5 years of TCS annual reports"
    at.chat_input[0].set_value(q).run()
    assert not at.exception
    assert agent.questions == [] and agent.fundamental.questions == [q]
    assert not any("not connected" in m.value for m in at.markdown)


def test_admin_is_locked_when_password_not_set(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path, password="")
    at.run()
    assert not at.exception
    text = " ".join(w.value for w in at.warning)
    assert "ARPM_ADMIN_PASSWORD" in text
    assert len(at.text_input) == 0 and len(at.button) == 0       # no password box, no way in


def test_admin_rejects_wrong_password_and_accepts_right_one(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    at.text_input(key="admin_pw").set_value("wrong")
    at.button(key="admin_login").click().run()
    assert any("incorrect" in e.value.lower() for e in at.error)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    assert not at.exception
    assert any(s.key == "role_chat_model" for s in at.text_input)


def test_admin_can_change_a_role_model(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    at.run()
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.text_input(key="role_chat_model").set_value("gemma4:e4b")
    at.button(key="role_chat_save").click().run()
    assert store.get_role("chat").model == "gemma4:e4b"
    assert store.audit_log(1)[0]["item"] == "role:chat"


def test_external_provider_cannot_be_chosen_until_enabled(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    at.run()
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.selectbox(key="role_chat_provider").set_value("huggingface")
    at.button(key="role_chat_save").click().run()
    assert any("not enabled" in e.value for e in at.error)
    assert store.get_role("chat").provider == "ollama_local"


def test_chunking_change_is_validated_and_warns_about_reindex(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    at.run()
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.number_input(key="chunk_size").set_value(100)
    at.button(key="chunk_save").click().run()
    assert any("200 to 8000" in e.value for e in at.error)
    assert store.get_value("chunking")["size"] == 1000


def test_footer_names_the_document_source_and_the_disclaimer(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    footer = " ".join(c.value for c in at.caption).lower()
    assert "annual reports" in footer and "transcripts" in footer
    assert "not investment advice" in footer
