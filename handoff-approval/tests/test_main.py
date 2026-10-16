"""Drive main.py with a fake workflow and scripted input. No Azure, no models.

These tests exist for one reason: the pause/answer loop is the pattern. If an
answer stops reaching the workflow, or a pause stops being recognised, the run
silently hangs instead of failing, so it needs to be pinned down here.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib
import sys
import types
from types import SimpleNamespace

import pytest


async def _done(value):
    """build() is awaited, so hand the fake workflow back from a coroutine."""
    return value


def event(text: str, who: str):
    return SimpleNamespace(
        type="intermediate", executor_id=who,
        data=SimpleNamespace(text=text, author_name=who),
    )


def user_pause(request_id: str, who: str, question: str):
    """An agent answered without handing off, so the workflow stops to ask."""
    return SimpleNamespace(
        type="request_info", executor_id=who, request_id=request_id,
        data=HandoffAgentUserRequest(question),
    )


class HandoffAgentUserRequest:
    """Mirrors the real dataclass: it carries the agent's response, and main.py
    recognises a user turn with `isinstance(data, HandoffAgentUserRequest)`."""

    def __init__(self, question: str):
        self.agent_response = SimpleNamespace(messages=[SimpleNamespace(text=question)])

    @staticmethod
    def create_response(message):
        return {"reply": message}

    @staticmethod
    def terminate():
        return []


class Content:
    """Stand-in for agent_framework.Content.

    Defined at module level, not inside the fixture, because main.py decides a
    pause is an approval with `isinstance(data, Content)` -- so the fake payload
    has to inherit from the very class installed into the fake module.
    """


class ApprovalData(Content):
    """A gated tool call, paused before it runs."""

    type = "function_approval_request"

    def __init__(self, name="approve_vehicle_financing", args=None):
        self.function_call = SimpleNamespace(
            name=name, parse_arguments=lambda: args or {"vehicle": "Honda CRV", "amount": 27000}
        )
        self.answered_with = None

    def to_function_approval_response(self, *, approved):
        self.answered_with = approved
        return {"framework_decision": approved}


def approval_pause(request_id: str, who: str, data=None):
    return SimpleNamespace(
        type="request_info", executor_id=who, request_id=request_id,
        data=data or ApprovalData(),
    )


class FakeFoundry:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeWorkflow:
    """Replays a script of turns; records every `responses` dict it is sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent: list[dict] = []
        self.started_with = None

    def run(self, message=None, *, stream=False, responses=None):
        assert stream is True
        if message is not None:
            self.started_with = message
        else:
            self.sent.append(responses)
        batch = self.turns.pop(0) if self.turns else []

        async def gen():
            for item in batch:
                yield item

        return gen()


@pytest.fixture
def build_harness(monkeypatch):
    """Returns a factory: give it the turns and the keystrokes, get main back."""

    def make(turns, keystrokes):
        workflow = FakeWorkflow(turns)
        foundry = FakeFoundry()

        agent_framework = types.ModuleType("agent_framework")
        orchestrations_module = types.ModuleType("agent_framework.orchestrations")

        agent_framework.Content = Content
        orchestrations_module.HandoffAgentUserRequest = HandoffAgentUserRequest
        monkeypatch.setitem(sys.modules, "agent_framework", agent_framework)
        monkeypatch.setitem(sys.modules, "agent_framework.orchestrations", orchestrations_module)

        orchestration = types.ModuleType("orchestrations.handoff_approval")
        orchestration.build = lambda _foundry, _tool_state: _done(workflow)
        monkeypatch.setitem(sys.modules, "orchestrations.handoff_approval", orchestration)

        foundry_module = types.ModuleType("services.foundry")

        class ConfigurationError(RuntimeError):
            pass

        foundry_module.ConfigurationError = ConfigurationError
        foundry_module.FoundryService = lambda: foundry
        monkeypatch.setitem(sys.modules, "services.foundry", foundry_module)

        typed = iter(keystrokes)
        monkeypatch.setattr(builtins, "input", lambda _prompt="": next(typed))

        sys.modules.pop("main", None)
        main = importlib.import_module("main")
        return main, workflow, foundry

    yield make
    sys.modules.pop("main", None)


def test_a_pause_is_answered_and_the_run_continues(build_harness, capsys):
    main, workflow, _foundry = build_harness(
        turns=[
            [event("Routing you.", "ReceptionAgent"),
             user_pause("req-1", "NewCarSpecialist", "What is your budget?")],
            [event("Here are three options.", "NewCarSpecialist")],
        ],
        keystrokes=["35000"],
    )
    asyncio.run(main.main())
    out = capsys.readouterr().out

    # The agent's question is surfaced to the user...
    assert "What is your budget?" in out
    # ...and the typed answer goes back keyed by the id of that exact request.
    assert workflow.sent == [{"req-1": {"reply": "35000"}}]
    assert "-- conversation complete --" in out


def test_the_loop_keeps_going_while_the_workflow_keeps_asking(build_harness):
    main, workflow, _foundry = build_harness(
        turns=[
            [user_pause("req-1", "A", "First?")],
            [user_pause("req-2", "B", "Second?")],
            [event("Done.", "B")],
        ],
        keystrokes=["one", "two"],
    )
    asyncio.run(main.main())
    assert workflow.sent == [
        {"req-1": {"reply": "one"}},
        {"req-2": {"reply": "two"}},
    ]


@pytest.mark.parametrize("word", ["quit", "exit", "QUIT"])
def test_quitting_terminates_the_request_rather_than_abandoning_it(build_harness, word):
    """Walking away is not enough: an unanswered request leaves the run suspended."""
    main, workflow, _foundry = build_harness(
        turns=[[user_pause("req-1", "A", "Anything else?")], []],
        keystrokes=[word],
    )
    asyncio.run(main.main())
    assert workflow.sent == [{"req-1": []}]


def test_a_run_that_never_pauses_needs_no_input(build_harness):
    main, workflow, _foundry = build_harness(
        turns=[[event("All handled.", "ReceptionAgent")]],
        keystrokes=[],  # asking for input would raise StopIteration
    )
    asyncio.run(main.main())
    assert workflow.sent == []


def test_foundry_is_closed_when_the_workflow_raises(build_harness):
    main, workflow, foundry = build_harness(turns=[], keystrokes=[])

    def boom(*_args, **_kwargs):
        async def gen():
            raise RuntimeError("workflow exploded")
            yield  # pragma: no cover - makes this an async generator

        return gen()

    workflow.run = boom
    with pytest.raises(RuntimeError):
        asyncio.run(main.main())
    assert foundry.closed is True


@pytest.mark.parametrize("keystroke, approved", [("y", True), ("yes", True), ("n", False)])
def test_an_approval_pause_is_answered_with_the_framework_response(
    build_harness, keystroke, approved
):
    """A tool pause is a different payload answered by a different call."""
    data = ApprovalData()
    main, workflow, _foundry = build_harness(
        turns=[[approval_pause("req-tool", "FinancingSpecialist", data)], []],
        keystrokes=[keystroke],
    )
    asyncio.run(main.main())
    assert data.answered_with is approved
    assert workflow.sent == [{"req-tool": {"framework_decision": approved}}]


def test_the_tool_call_is_shown_before_the_decision(build_harness, capsys):
    main, _workflow, _foundry = build_harness(
        turns=[[approval_pause("req-tool", "FinancingSpecialist")], []],
        keystrokes=["n"],
    )
    asyncio.run(main.main())
    out = capsys.readouterr().out
    assert "APPROVAL NEEDED" in out
    assert "approve_vehicle_financing" in out
    assert "Honda CRV" in out  # you can see what you are approving


def test_rejecting_reports_that_the_tool_never_executed(build_harness, capsys):
    """tool_state is written by the tool itself, so this is the honest check."""
    main, _workflow, _foundry = build_harness(
        turns=[[approval_pause("req-tool", "FinancingSpecialist")], []],
        keystrokes=["n"],
    )
    asyncio.run(main.main())
    assert "tool executed: False" in capsys.readouterr().out


def test_both_kinds_of_pause_are_handled_in_one_run(build_harness):
    """The bug this guards: handling only user pauses strands an approval."""
    data = ApprovalData()
    main, workflow, _foundry = build_harness(
        turns=[
            [user_pause("req-1", "NewCarSpecialist", "Your name?")],
            [approval_pause("req-tool", "FinancingSpecialist", data)],
            [event("All set.", "FinancingSpecialist")],
        ],
        keystrokes=["Alex", "y"],
    )
    asyncio.run(main.main())
    assert workflow.sent == [
        {"req-1": {"reply": "Alex"}},
        {"req-tool": {"framework_decision": True}},
    ]


def test_an_unknown_request_type_fails_loudly(build_harness):
    """The framework has other request kinds (computer_tool_call). None are used
    here, so one arriving means an assumption broke -- it must not be mistaken
    for a user turn and crash later inside question()."""

    class Unknown(Content):
        type = "computer_tool_call"

    unknown = SimpleNamespace(
        type="request_info", executor_id="X", request_id="req-odd", data=Unknown()
    )
    main, workflow, _foundry = build_harness(turns=[[unknown]], keystrokes=[])
    with pytest.raises(RuntimeError, match="Unsupported request type: computer_tool_call"):
        asyncio.run(main.main())
    assert workflow.sent == []
