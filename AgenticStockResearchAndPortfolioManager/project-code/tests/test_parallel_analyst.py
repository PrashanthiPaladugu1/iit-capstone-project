"""The research analyst can run the technical and fundamental agents at the same time.

Covers the three shared pieces that threads touch: Budget (counters, depth), the gateway's last cost, and the analyst itself.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_research_analyst import ResearchAnalyst  # noqa: E402
from agent_technical import TechnicalResult  # noqa: E402
from budget import Budget, BudgetExceeded  # noqa: E402
from test_agent_research_analyst import GOOD_NOTE, SPLIT_OK, ScriptedGateway, say  # noqa: E402


def in_threads(count, fn):
    threads = [threading.Thread(target=fn) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ----------------------------------------------------------------------------------- Budget
def test_budget_counters_do_not_lose_updates_under_threads():
    b = Budget(max_model_calls=10**6, max_tool_calls=10**6, max_tokens=10**9)

    def work():
        for _ in range(2000):
            b.after_model_call(3, 2, 0.5)
            b.before_tool_call()

    in_threads(8, work)
    assert b.model_calls == 16000 and b.tool_calls == 16000 and b.tokens == 16000 * 5
    assert b.cost == pytest.approx(8000.0)


def test_tool_call_limit_is_exact_under_threads():
    b = Budget(max_tool_calls=100)
    allowed, refused = [], []

    def work():
        for _ in range(50):
            try:
                b.before_tool_call()
                allowed.append(1)
            except BudgetExceeded:
                refused.append(1)

    in_threads(8, work)
    assert len(allowed) == 100 and len(refused) == 300 and b.tool_calls == 100


def test_two_branches_are_both_one_level_below_their_parent():
    b = Budget()                                            # max depth 3
    b.enter_agent("analyst")                                # depth 1
    base = b.current_depth()
    seen, ready = [], threading.Barrier(2, timeout=5)

    def branch():
        with b.branch(base):
            b.enter_agent("specialist")
            ready.wait()                                    # both specialists are inside at the same moment
            seen.append(b.current_depth())
            b.leave_agent()

    in_threads(2, branch)
    assert seen == [2, 2]                                   # not 2 and 3
    assert b.depth == 1 and b.current_depth() == 1          # the parent's depth is untouched


def test_a_branch_still_obeys_the_depth_limit():
    b = Budget(max_depth=2)
    b.enter_agent("analyst")
    errors = []

    def branch():
        with b.branch(b.current_depth()):
            b.enter_agent("specialist")                     # depth 2: allowed
            try:
                b.enter_agent("too deep")                   # depth 3: refused
            except BudgetExceeded as exc:
                errors.append(str(exc))

    in_threads(1, branch)
    assert errors and "depth limit" in errors[0]


def test_enter_and_leave_on_the_main_thread_work_as_before():
    b = Budget()
    b.enter_agent("a")
    b.enter_agent("b")
    assert b.depth == 2
    b.leave_agent()
    b.leave_agent()
    b.leave_agent()                                         # never below zero
    assert b.depth == 0


# ----------------------------------------------------------------------------------- gateway cost
def test_gateway_last_cost_is_per_thread(tmp_path):
    from gateway import Gateway
    from model_settings import SettingsStore
    gw = Gateway(SettingsStore(tmp_path / "s.sqlite"), tmp_path / "u.sqlite")
    gw._last_cost = 1.5
    seen = []
    in_threads(1, lambda: seen.append(gw._last_cost))
    assert seen == [None] and gw._last_cost == 1.5          # another thread does not see, or overwrite, this thread's cost


# ----------------------------------------------------------------------------------- the analyst
class MeetingSpecialist:
    """Waits for the other specialist at a barrier. It can only finish if both run at the same time."""

    def __init__(self, name, answer, barrier=None, delay=0.0, error=None):
        self.agent_name, self.answer, self.barrier, self.delay, self.error = name, answer, barrier, delay, error
        self.thread, self.calls = None, []

    def run(self, question, *, session="", parent_call_id=None, budget=None, route="", focus="", **kw):
        self.thread = threading.current_thread().name
        self.calls.append({"question": question, "parent": parent_call_id, "depth": budget.current_depth()})
        if self.barrier:
            self.barrier.wait()
        time.sleep(self.delay)
        if self.error:
            raise self.error
        budget.after_model_call(100, 10)
        return TechnicalResult(answer=self.answer, tool_trace=[{"tool": f"{self.agent_name}_tool", "arguments": {}}],
                               budget=budget.summary(), call_ids=[len(self.answer)])


def analyst_with(tech, fund, *gateway_results, **kw):
    return ResearchAnalyst(ScriptedGateway(*gateway_results), tech, fund, **kw)


TECH_TEXT = "ITC RSI is 55.2 (data to 13 Nov 2026)."
FUND_TEXT = "ITC revenue grew 8.7% a year over 5 years."


def test_both_specialists_run_at_the_same_time_in_parallel_mode():
    meet = threading.Barrier(2, timeout=5)                  # raises BrokenBarrierError if they run one after the other
    tech = MeetingSpecialist("agent_technical", TECH_TEXT, meet)
    fund = MeetingSpecialist("agent_fundamental", FUND_TEXT, meet)
    out = analyst_with(tech, fund, say(SPLIT_OK), say(GOOD_NOTE), parallel=True).run("q")
    assert out.answer == GOOD_NOTE and not out.stopped_early
    assert tech.thread != fund.thread


def test_parallel_mode_gives_the_same_answer_trace_and_budget_as_sequential_mode():
    outs = []
    for parallel in (False, True):
        tech = MeetingSpecialist("agent_technical", TECH_TEXT, delay=0.05)
        fund = MeetingSpecialist("agent_fundamental", FUND_TEXT)        # finishes first when parallel
        outs.append(analyst_with(tech, fund, say(SPLIT_OK), say(GOOD_NOTE), parallel=parallel).run("q"))
    seq, par = outs
    assert seq.answer == par.answer
    assert [t["agent"] for t in par.tool_trace] == ["research", "technical", "research", "fundamental"]   # plan order, not finishing order
    assert seq.tool_trace == par.tool_trace
    assert seq.budget == par.budget and par.budget["model_calls"] == 4
    assert par.call_ids == seq.call_ids


def test_sequential_mode_runs_on_the_calling_thread_one_after_the_other():
    tech = MeetingSpecialist("agent_technical", TECH_TEXT)
    fund = MeetingSpecialist("agent_fundamental", FUND_TEXT)
    analyst_with(tech, fund, say(SPLIT_OK), say(GOOD_NOTE), parallel=False).run("q")
    assert tech.thread == fund.thread == threading.current_thread().name


def test_parallel_specialists_are_children_of_the_split_call_and_one_level_below_the_analyst():
    tech = MeetingSpecialist("agent_technical", TECH_TEXT)
    fund = MeetingSpecialist("agent_fundamental", FUND_TEXT)
    analyst_with(tech, fund, say(SPLIT_OK), say(GOOD_NOTE), parallel=True).run("q")
    assert tech.calls[0]["parent"] == fund.calls[0]["parent"] == 101
    assert tech.calls[0]["depth"] == fund.calls[0]["depth"] == 1


def test_one_part_only_runs_that_specialist_without_a_thread_pool():
    only_tech = '{"technical": "RSI of ITC?", "fundamental": ""}'
    tech = MeetingSpecialist("agent_technical", TECH_TEXT)
    fund = MeetingSpecialist("agent_fundamental", FUND_TEXT)
    out = analyst_with(tech, fund, say(only_tech), parallel=True).run("q")
    assert out.answer == TECH_TEXT and not fund.calls and tech.thread == threading.current_thread().name


def test_a_budget_error_in_one_parallel_specialist_ends_the_run_cleanly():
    tech = MeetingSpecialist("agent_technical", TECH_TEXT, delay=0.05)
    fund = MeetingSpecialist("agent_fundamental", FUND_TEXT, error=BudgetExceeded("tool call limit reached (40)"))
    out = analyst_with(tech, fund, say(SPLIT_OK), say(GOOD_NOTE), parallel=True).run("q")
    assert out.answer.startswith("I could not finish this") and "tool call limit" in out.stopped_early


def test_parallel_is_the_default_choice_that_the_constructor_exposes():
    analyst = analyst_with(MeetingSpecialist("t", "a"), MeetingSpecialist("f", "b"))
    assert isinstance(analyst.parallel, bool)
