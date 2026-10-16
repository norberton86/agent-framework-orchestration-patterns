"""The handoff pattern, end to end, in a terminal.

Run it:  .venv/bin/python main.py

This is the whole lesson. A handoff workflow does not simply run to completion:
an agent can transfer to a specialist **or** keep serving the customer, and
transfers happen through a tool call. So when an agent writes a reply *instead
of* calling a handoff tool, the workflow has no edge to follow and stops to ask
you. That pause is a `request_info` event carrying a `HandoffAgentUserRequest`,
and the run stays suspended until you answer it, keyed by its `request_id`.

Worth knowing if you later wrap this in a web app: a browser cannot hold a
suspended workflow between two HTTP requests, so a server has to store the
pending request in a session, run the workflow on a loop it owns, and expose a
second endpoint to resume. None of that is handoff -- it is the cost of the
transport. A terminal has no such problem, which is why the whole pattern fits
in one readable file here.
"""

import asyncio

from dotenv import load_dotenv

from agent_framework.orchestrations import HandoffAgentUserRequest

from orchestrations import handoff as orchestration
from services.foundry import ConfigurationError, FoundryService

OPENING = "I need a new family SUV"
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


def question(request) -> str:
    """The agent's most recent message — what it is actually waiting on."""
    messages = getattr(request.data.agent_response, "messages", [])
    return messages[-1].text if messages else ""


async def collect(stream):
    """Drain one run: print what the agents say, return the pause if there is one.

    Returns the `request_info` event the workflow stopped on, or None if the run
    finished on its own. One agent owns a handoff conversation at a time, so a
    pause never carries two questions -- a second one would mean an assumption
    here is wrong, and saying so beats silently dropping it.
    """
    speaker = None
    pending = None
    async for event in stream:
        if event.type == "request_info":
            if pending is not None:
                raise RuntimeError("A handoff pause should never carry two requests.")
            pending = event                 # the workflow is suspended here
        else:
            speaker = show(event, speaker)
    return pending


async def main() -> None:
    load_dotenv()
    foundry = FoundryService()
    workflow = await orchestration.build(foundry)
    print(f"[You]\n{OPENING}", flush=True)

    try:
        # --- first turn -------------------------------------------------
        request = await collect(workflow.run(OPENING, stream=True))

        # --- answer each pause until the workflow stops asking -----------
        while request is not None:
            print(f"\n\n? {question(request)}\n", flush=True)
            # Blocking input is fine here: nothing else is running on this loop.
            reply = input("You: ").strip()

            # Ending early still means *answering* the request: the workflow
            # has to be told, or it simply stays suspended.
            answer = (
                HandoffAgentUserRequest.terminate()
                if reply.lower() in QUIT
                else HandoffAgentUserRequest.create_response(reply)
            )

            # Keyed by request_id so the workflow matches the answer to the
            # exact request it raised.
            request = await collect(workflow.run(responses={request.request_id: answer}, stream=True))

        # No request came back, so the run is genuinely over.
        print("\n\n-- conversation complete --")
    finally:
        await foundry.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigurationError as error:
        raise SystemExit(f"{error}\nCopy .env.example to .env, then run: az login")
    except KeyboardInterrupt:
        print()
