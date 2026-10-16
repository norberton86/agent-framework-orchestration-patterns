"""Handoff + tool approval, end to end, in a terminal.

Run it:  .venv/bin/python main.py

This is the whole lesson. A handoff workflow does not simply run to completion:
an agent can transfer to a specialist **or** keep serving the customer, and
transfers happen through a tool call. So when an agent writes a reply *instead
of* calling a handoff tool, the workflow has no edge to follow and stops to ask
you. That pause is a `request_info` event carrying a `HandoffAgentUserRequest`,
and the run stays suspended until you answer it, keyed by its `request_id`.

**Two different things pause this workflow, and both arrive as `request_info`.**
An agent waiting on the customer, and a tool marked
`@tool(approval_mode="always_require")` waiting on a human decision. They are
answered by different calls, so the loop below has to tell them apart. Handling
only the first is the classic bug: the approval is dropped, the loop exits, and
the workflow sits suspended with no error to explain why.

Worth knowing if you later wrap this in a web app: a browser cannot hold a
suspended workflow between two HTTP requests, so a server has to store the
pending request in a session, run the workflow on a loop it owns, and expose a
second endpoint to resume. None of that is handoff -- it is the cost of the
transport. A terminal has no such problem, which is why the whole pattern fits
in one readable file here.
"""

import asyncio

from dotenv import load_dotenv

from agent_framework import Content
from agent_framework.orchestrations import HandoffAgentUserRequest

from orchestrations import handoff_approval as orchestration
from services.foundry import ConfigurationError, FoundryService

OPENING = "I want a new Honda CRV and need financing"
QUIT = {"quit", "exit"}


def show(event, last_speaker: str | None) -> str | None:
    """Print one streamed chunk of agent text; return whoever spoke.

    The caller passes back what this returned last time, so a name is printed
    only when the speaker actually changes rather than on every chunk.
    """
    text = getattr(event.data, "text", "") or ""
    if not text:
        return last_speaker            # lifecycle events carry no text
    speaker = getattr(event.data, "author_name", None) or event.executor_id
    if speaker != last_speaker:
        print(f"\n\n[{speaker}]", flush=True)
    print(text, end="", flush=True)
    return speaker


def is_approval(request) -> bool:
    """Is this pause a gated tool waiting on a human?"""
    return isinstance(request.data, Content) and request.data.type == "function_approval_request"


def is_user_turn(request) -> bool:
    """Is this pause an agent waiting on the customer?"""
    return isinstance(request.data, HandoffAgentUserRequest)


def question(request) -> str:
    """The agent's most recent message — what it is actually waiting on."""
    messages = getattr(request.data.agent_response, "messages", [])
    return messages[-1].text if messages else ""


def tool_summary(request) -> str:
    """What the gated tool is about to be called with."""
    call = request.data.function_call
    try:
        args = call.parse_arguments() or {}
    except (TypeError, ValueError):
        args = {}
    shown = ", ".join(f"{k}={v!r}" for k, v in args.items()) or "no arguments"
    return f"{call.name}({shown})"


async def collect(stream) -> list:
    """Drain one run: print what the agents say, return any pauses.

    A list, not a single value: one agent response can contain several gated
    tool calls, and each becomes its own request. (The plain handoff project
    returns one, because an agent waiting on the customer only ever asks once.)
    """
    speaker = None
    pending: list = []
    async for event in stream:
        if event.type == "request_info":
            pending.append(event)          # the workflow is suspended here
        else:
            speaker = show(event, speaker)
    return pending


async def main() -> None:
    load_dotenv()
    foundry = FoundryService()
    # The tool writes into this dict when it actually runs, so at the end we can
    # state plainly whether an approved call executed -- rather than trusting the
    # model's description of what it did.
    tool_state: dict = {}
    workflow = await orchestration.build(foundry, tool_state)
    print(f"[You]\n{OPENING}", flush=True)

    try:
        # --- first turn -------------------------------------------------
        pending = await collect(workflow.run(OPENING, stream=True))

        # --- answer each pause until the workflow stops asking -----------
        while pending:
            responses = {}
            for request in pending:
                # Blocking input is fine here: nothing else is running on this
                # loop. A web app cannot do this, which is why it has to store
                # the request and wait for a second HTTP call instead.
                if is_approval(request):
                    # A tool is paused mid-call. Rejecting is a real answer, not
                    # a cancellation: the workflow resumes either way.
                    print(f"\n\nAPPROVAL NEEDED\n  {tool_summary(request)}\n", flush=True)
                    approved = input("Approve? (y/n): ").strip().lower().startswith("y")
                    responses[request.request_id] = request.data.to_function_approval_response(
                        approved=approved
                    )
                elif is_user_turn(request):
                    print(f"\n\n? {question(request)}\n", flush=True)
                    reply = input("You: ").strip()
                    # Ending early still means *answering* the request: the
                    # workflow has to be told, or it simply stays suspended.
                    responses[request.request_id] = (
                        HandoffAgentUserRequest.terminate()
                        if reply.lower() in QUIT
                        else HandoffAgentUserRequest.create_response(reply)
                    )
                else:
                    # The framework has other request types (computer_tool_call,
                    # for one). No agent here uses them, so reaching this means
                    # an assumption is wrong -- say so rather than crash later
                    # inside question() with an attribute error.
                    kind = getattr(request.data, "type", type(request.data).__name__)
                    raise RuntimeError(f"Unsupported request type: {kind}")

            # Keyed by request_id so the workflow matches each answer to the
            # exact request it raised.
            pending = await collect(workflow.run(responses=responses, stream=True))

        # No request came back, so the run is genuinely over.
        print("\n\n-- conversation complete --")
        print(f"   tool executed: {bool(tool_state.get('executed'))}")
        if tool_state.get("record"):
            print(f"   recorded: {tool_state['record']}")
    finally:
        await foundry.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigurationError as error:
        raise SystemExit(f"{error}\nCopy .env.example to .env, then run: az login")
    except KeyboardInterrupt:
        print()
