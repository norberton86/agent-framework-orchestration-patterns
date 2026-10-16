"""Drive main.py with a fake workflow. No Azure account, no model calls."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

import pytest


def event(text: str, who: str):
    """One streamed chunk of agent text, shaped like the framework emits."""
    return SimpleNamespace(
        type="intermediate", executor_id=who,
        data=SimpleNamespace(text=text, author_name=who),
    )


class FakeWorkflow:
    """Yields three agents' output and finishes. Nothing pauses: that is the point."""

    def __init__(self, events):
        self.events = events
        self.started_with = None

    def run(self, message=None, *, stream=False, responses=None):
        assert stream is True
        self.started_with = message

        async def gen():
            for item in self.events:
                yield item

        return gen()


class FakeFoundry:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.fixture
def harness(monkeypatch):
    """Import main.py with its Foundry and orchestration dependencies faked out."""
    workflow = FakeWorkflow([event("Part one. ", "InventoryAgent"), event("Part two.", "InventoryAgent"), event("Result.", "PricingAgent"), event("Result.", "DeliveryAgent")])
    foundry = FakeFoundry()

    orchestration = types.ModuleType("orchestrations.concurrent")

    async def build(_foundry):
        return workflow

    orchestration.build = build
    monkeypatch.setitem(sys.modules, "orchestrations.concurrent", orchestration)

    foundry_module = types.ModuleType("services.foundry")

    class ConfigurationError(RuntimeError):
        pass

    foundry_module.ConfigurationError = ConfigurationError
    foundry_module.FoundryService = lambda: foundry
    monkeypatch.setitem(sys.modules, "services.foundry", foundry_module)

    # main.py takes an optional request as argv[1]; under pytest argv holds
    # pytest's own arguments, so pin it to "no argument supplied".
    monkeypatch.setattr(sys, "argv", ["main.py"])

    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    yield main, workflow, foundry
    sys.modules.pop("main", None)


def test_every_agent_is_shown(harness, capsys):
    main, _workflow, _foundry = harness
    asyncio.run(main.main())
    out = capsys.readouterr().out
    for name in ["InventoryAgent", "PricingAgent", "DeliveryAgent"]:
        assert f"[{name}]" in out
    assert "-- done --" in out


def test_speakers_appear_in_the_order_the_workflow_emitted(harness, capsys):
    main, _workflow, _foundry = harness
    asyncio.run(main.main())
    out = capsys.readouterr().out
    positions = [out.index(f"[{name}]") for name in ["InventoryAgent", "PricingAgent", "DeliveryAgent"]]
    assert positions == sorted(positions)


def test_a_speaker_is_announced_once_not_per_chunk(harness, capsys):
    """Text arrives in chunks; the label should not repeat for the same agent."""
    main, _workflow, _foundry = harness
    asyncio.run(main.main())
    out = capsys.readouterr().out
    assert out.count("[InventoryAgent]") == 1


def test_the_default_request_reaches_the_workflow(harness):
    main, workflow, _foundry = harness
    asyncio.run(main.main())
    assert workflow.started_with == main.REQUEST


def test_a_request_given_on_the_command_line_wins(harness, monkeypatch):
    main, workflow, _foundry = harness
    monkeypatch.setattr(sys, "argv", ["main.py", "something else entirely"])
    asyncio.run(main.main())
    assert workflow.started_with == "something else entirely"


def test_foundry_is_closed_even_though_nothing_failed(harness):
    """close() deletes the CSVs uploaded for the run, so it must always happen."""
    main, _workflow, foundry = harness
    asyncio.run(main.main())
    assert foundry.closed is True


def test_foundry_is_closed_when_the_workflow_raises(harness, monkeypatch):
    main, workflow, foundry = harness

    def boom(*_args, **_kwargs):
        async def gen():
            raise RuntimeError("workflow exploded")
            yield  # pragma: no cover - makes this an async generator

        return gen()

    monkeypatch.setattr(workflow, "run", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(main.main())
    assert foundry.closed is True
