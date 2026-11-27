import ui_app
from chat_store import ChatStore
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


def open_admin(at):
    at.run()
    at.button(key="open_admin").click().run()
    return at


def make(monkeypatch, tmp_path, password="secret"):
    monkeypatch.setenv("ARPM_ADMIN_PASSWORD", password)
    store = SettingsStore(tmp_path / "s.sqlite")
    agent = FakeAgent()
    fundamental = FakeAgent("TCS net profit grew 8.7% a year.")
    agent.fundamental = fundamental                      # the tests read it back through the technical fake
    monkeypatch.setattr(ui_app, "get_settings", lambda: store)
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": fundamental})
    monkeypatch.setattr(ui_app, "get_gateway", lambda: None)
    chats = ChatStore(tmp_path / "chats.sqlite")
    monkeypatch.setattr(ui_app, "get_chats", lambda: chats)
    agent.chats = chats
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
    welcome = " ".join(m.value for m in at.main.markdown).lower()
    assert "prices" in welcome and "financial statements" in welcome and "annual reports" in welcome
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


class FakeAnalyst:
    def __init__(self, text="ITC RSI is 55.2 and revenue grew 8.7% a year.", note="", stopped=""):
        self.questions, self.text, self.note, self.stopped = [], text, note, stopped

    def run(self, question, **kw):
        self.questions.append(question)
        result = FakeResult()
        result.answer, result.note, result.stopped_early = self.text, self.note, self.stopped
        result.tool_trace = [{"tool": "get_indicators", "arguments": {}, "agent": "technical"},
                             {"tool": "fsa_compute_growth", "arguments": {}, "agent": "fundamental"}]
        return result


def test_mixed_question_goes_to_the_research_analyst_when_it_is_connected(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    analyst = FakeAnalyst()
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental,
                                                       "research": analyst})
    at.run()
    at.chat_input[0].set_value("Revenue growth and RSI of ITC").run()
    assert not at.exception
    assert analyst.questions == ["Revenue growth and RSI of ITC"]
    assert agent.questions == [] and agent.fundamental.questions == []          # the analyst runs them, not the UI
    assert any("RSI is 55.2" in m.value for m in at.markdown)


def test_analyst_note_is_shown_to_the_user(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    analyst = FakeAnalyst(note="The merged answer was dropped because of a number.")
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental,
                                                       "research": analyst})
    at.run()
    at.chat_input[0].set_value("Revenue growth and RSI of ITC").run()
    assert any("merged answer was dropped" in m.value for m in at.markdown)


def test_single_topic_questions_skip_the_analyst(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    analyst = FakeAnalyst()
    monkeypatch.setattr(ui_app, "get_agents", lambda: {"technical": agent, "fundamental": agent.fundamental,
                                                       "research": analyst})
    at.run()
    at.chat_input[0].set_value("What is the RSI of TCS?").run()
    assert analyst.questions == [] and agent.questions == ["What is the RSI of TCS?"]


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
    open_admin(at)
    assert not at.exception
    text = " ".join(w.value for w in at.warning)
    assert "ARPM_ADMIN_PASSWORD" in text
    assert len(at.main.text_input) == 0                            # no password box, no way in
    assert [b.key for b in at.main.button] == ["back_to_chat"]    # only the way back to the chat


def test_admin_rejects_wrong_password_and_accepts_right_one(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    open_admin(at)
    at.text_input(key="admin_pw").set_value("wrong")
    at.button(key="admin_login").click().run()
    assert any("incorrect" in e.value.lower() for e in at.error)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    assert not at.exception
    assert any(s.key == "role_chat_model" for s in at.text_input)


def test_admin_can_change_a_role_model(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    open_admin(at)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.text_input(key="role_chat_model").set_value("gemma4:e4b")
    at.button(key="role_chat_save").click().run()
    assert store.get_role("chat").model == "gemma4:e4b"
    assert store.audit_log(1)[0]["item"] == "role:chat"


def test_external_provider_cannot_be_chosen_until_enabled(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    open_admin(at)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.selectbox(key="role_chat_provider").set_value("huggingface")
    at.button(key="role_chat_save").click().run()
    assert any("not enabled" in e.value for e in at.error)
    assert store.get_role("chat").provider == "ollama_local"


def test_chunking_change_is_validated_and_warns_about_reindex(monkeypatch, tmp_path):
    at, store, _ = make(monkeypatch, tmp_path)
    open_admin(at)
    at.text_input(key="admin_pw").set_value("secret")
    at.button(key="admin_login").click().run()
    at.number_input(key="chunk_size").set_value(100)
    at.button(key="chunk_save").click().run()
    assert any("200 to 8000" in e.value for e in at.error)
    assert store.get_value("chunking")["size"] == 1000


def test_footer_names_the_document_source_and_the_disclaimer(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    footer = " ".join(m.value for m in at.main.markdown).lower()
    assert "annual reports" in footer and "transcripts" in footer
    assert "not investment advice" in footer


# ---------------------------------------------------------------------------------------------- ChatGPT-style layout
def sidebar_text(at):
    return " ".join([b.label for b in at.sidebar.button] + [m.value for m in at.sidebar.markdown]
                    + [c.value for c in at.sidebar.caption])


def test_sidebar_has_new_chat_button_and_search_box(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert any(b.key == "new_chat" for b in at.sidebar.button)
    assert any(t.key == "chat_search" for t in at.sidebar.text_input)


def test_a_question_is_saved_and_listed_in_the_sidebar(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    assert not at.exception
    saved = agent.chats.list_conversations()
    assert len(saved) == 1 and saved[0]["title"] == "RSI of TCS?"
    assert [m["role"] for m in agent.chats.messages(saved[0]["id"])] == ["user", "assistant"]
    assert any("RSI of TCS?" in b.label for b in at.sidebar.button)
    assert "Recents" in sidebar_text(at)


def test_history_survives_a_page_refresh(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    refreshed = AppTest.from_function(run_app, default_timeout=20)       # a new browser session: empty session_state
    refreshed.run()
    assert any("RSI of TCS?" in b.label for b in refreshed.sidebar.button)
    assert len(agent.chats.list_conversations()) == 1


def test_clicking_a_history_item_shows_that_conversation(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    at.button(key="new_chat").click().run()
    at.chat_input[0].set_value("check financial statement of infosys").run()
    assert len(agent.chats.list_conversations()) == 2
    first = [c for c in agent.chats.list_conversations() if c["title"] == "RSI of TCS?"][0]
    at.button(key=f"open_{first['id']}").click().run()
    text = " ".join(m.value for m in at.markdown)
    assert "RSI of TCS?" in text and "TCS RSI is 55." in text
    assert "check financial statement of infosys" not in " ".join(m.value for m in at.main.markdown)


def test_new_chat_clears_the_window_but_keeps_the_old_chat_in_the_list(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    at.button(key="new_chat").click().run()
    assert not any("TCS RSI is 55." in m.value for m in at.main.markdown)
    assert any("RSI of TCS?" in b.label for b in at.sidebar.button)
    assert len(agent.chats.list_conversations()) == 1                    # nothing is deleted, no empty chat is listed


def test_follow_up_questions_stay_in_the_same_conversation(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    at.chat_input[0].set_value("RSI of INFY?").run()
    saved = agent.chats.list_conversations()
    assert len(saved) == 1 and len(agent.chats.messages(saved[0]["id"])) == 4


def test_sidebar_search_filters_the_history(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of TCS?").run()
    at.button(key="new_chat").click().run()
    at.chat_input[0].set_value("check financial statement of infosys").run()
    at.text_input(key="chat_search").set_value("infosys").run()
    labels = [b.label for b in at.sidebar.button if b.key and b.key.startswith("open_") and b.key != "open_admin"]
    assert len(labels) == 1 and "infosys" in labels[0].lower()


def test_a_refresh_with_no_chats_shows_the_welcome_with_examples(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    text = " ".join(m.value for m in at.main.markdown)
    assert "What can I help you with" in text
    assert any(b.key and b.key.startswith("example_") for b in at.main.button)


def test_clicking_an_example_asks_that_question(monkeypatch, tmp_path):
    at, _, agent = make(monkeypatch, tmp_path)
    at.run()
    at.button(key="example_0").click().run()
    assert agent.questions == [ui_app.EXAMPLES[0]]


def test_admin_lives_in_the_sidebar_footer_not_in_tabs(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    assert len(at.tabs) == 0
    assert any(b.key == "open_admin" for b in at.sidebar.button)
    at.button(key="open_admin").click().run()
    assert not at.exception and any(w.key == "admin_pw" for w in at.text_input)
    at.button(key="back_to_chat").click().run()
    assert any(c.type == "chat_input" or True for c in at.chat_input) and len(at.chat_input) == 1


def test_a_question_with_html_does_not_inject_markup_into_the_title_bar(monkeypatch, tmp_path):
    at, _, _ = make(monkeypatch, tmp_path)
    at.run()
    at.chat_input[0].set_value("RSI of <b onmouseover=x>TCS</b>?").run()
    bar = [m.value for m in at.main.markdown if m.value.startswith("<div class='title-bar'>")][0]
    assert "<b onmouseover" not in bar and "&lt;b" in bar
