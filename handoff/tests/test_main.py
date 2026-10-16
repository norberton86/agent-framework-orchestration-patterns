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
        data=UserRequestData(question),
    )


class UserRequestData:
    def __init__(self, question: str):
        self.agent_response = SimpleNamespace(messages=[SimpleNamespace(text=question)])


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

        class Content:
            pass

        class HandoffAgentUserRequest:
            @staticmethod
            def create_response(message):
                return {"reply": message}

            @staticmethod
            def terminate():
                return {"terminated": True}

        agent_framework.Content = Content
        orchestrations_module.HandoffAgentUserRequest = HandoffAgentUserRequest
        monkeypatch.setitem(sys.modules, "agent_framework", agent_framework)
        monkeypatch.setitem(sys.modules, "agent_framework.orchestrations", orchestrations_module)

        orchestration = types.ModuleType("orchestrations.handoff")
        orchestration.build = lambda _foundry: _done(workflow)
        monkeypatch.setitem(sys.modules, "orchestrations.handoff", orchestration)

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
    assert workflow.sent == [{"req-1": {"terminated": True}}]


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
