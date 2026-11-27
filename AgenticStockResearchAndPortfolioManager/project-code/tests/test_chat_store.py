"""chat_store: conversations and their messages, kept in SQLite so the sidebar history survives a refresh and a restart."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chat_store import ChatStore, group_label  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return ChatStore(tmp_path / "chats.sqlite")


def test_new_conversation_starts_empty_with_a_default_title(store):
    cid = store.new_conversation()
    assert store.messages(cid) == []
    assert store.get(cid)["title"] == "New chat"


def test_first_user_message_becomes_the_title_and_is_shortened(store):
    cid = store.new_conversation()
    store.add_message(cid, "user", "How has TCS net profit grown over the last five years and what drove it?")
    title = store.get(cid)["title"]
    assert title.startswith("How has TCS net profit") and len(title) <= 50 and title.endswith("...")
    store.add_message(cid, "user", "second question")
    assert store.get(cid)["title"] == title                                   # only the first message names the chat


def test_messages_come_back_in_order_with_trace_and_budget(store):
    cid = store.new_conversation()
    store.add_message(cid, "user", "RSI of TCS?")
    store.add_message(cid, "assistant", "50.39", trace=[{"tool": "get_indicators", "arguments": {"symbol": "TCS"}}],
                      budget={"model_calls": 2}, route="technical", stopped="")
    got = store.messages(cid)
    assert [m["role"] for m in got] == ["user", "assistant"]
    assert got[1]["text"] == "50.39" and got[1]["route"] == "technical"
    assert got[1]["trace"][0]["tool"] == "get_indicators" and got[1]["budget"] == {"model_calls": 2}


def test_list_is_newest_first_and_a_new_message_moves_a_chat_to_the_top(store):
    a, b = store.new_conversation(), store.new_conversation()
    store.add_message(a, "user", "first chat")
    time.sleep(0.01)
    store.add_message(b, "user", "second chat")
    assert [c["id"] for c in store.list_conversations()] == [b, a]
    time.sleep(0.01)
    store.add_message(a, "assistant", "reply")
    assert [c["id"] for c in store.list_conversations()] == [a, b]


def test_empty_conversations_are_not_listed(store):
    store.new_conversation()
    assert store.list_conversations() == []


def test_search_matches_titles_and_message_text(store):
    a, b = store.new_conversation(), store.new_conversation()
    store.add_message(a, "user", "RSI of TCS?")
    store.add_message(b, "user", "annual report risks")
    store.add_message(b, "assistant", "Cyber threats are a key risk at Reliance.")
    assert [c["id"] for c in store.list_conversations(query="rsi")] == [a]
    assert [c["id"] for c in store.list_conversations(query="cyber")] == [b]
    assert store.list_conversations(query="nothing like this") == []


def test_search_text_is_not_treated_as_sql_or_a_wildcard(store):
    cid = store.new_conversation()
    store.add_message(cid, "user", "100% growth")
    assert store.list_conversations(query="%") != [] and store.list_conversations(query="x'; --") == []
    other = store.new_conversation()
    store.add_message(other, "user", "plain text")
    assert [c["id"] for c in store.list_conversations(query="%")] == [cid]    # % is a literal, not "match all"


def test_unknown_conversation(store):
    assert store.get("nope") is None and store.messages("nope") == []
    with pytest.raises(KeyError):
        store.add_message("nope", "user", "hi")


def test_two_stores_on_one_file_see_the_same_data(tmp_path):
    first = ChatStore(tmp_path / "c.sqlite")
    cid = first.new_conversation()
    first.add_message(cid, "user", "hello")
    assert ChatStore(tmp_path / "c.sqlite").messages(cid)[0]["text"] == "hello"


def test_group_labels_follow_the_calendar_day():
    now = time.mktime((2026, 11, 20, 15, 0, 0, 0, 0, -1))
    day = 86400
    assert group_label(now - 3600, now) == "Today"
    assert group_label(now - day, now) == "Yesterday"
    assert group_label(now - 3 * day, now) == "Previous 7 days"
    assert group_label(now - 20 * day, now) == "Older"
