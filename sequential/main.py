"""The sequential pattern, end to end, in a terminal.

Run it:  .venv/bin/python main.py  ["your request"]

`SequentialBuilder` wires the agents into a pipeline. Each one receives
everything the previous one produced, so the order is fixed before the run
starts and every agent speaks exactly once, in turn. Watch the speaker change
in order below: PetReceptionist, then PetExpert, then AdoptionAdvisor.

Notice what is *absent*: there is no pause to handle, no request id to answer,
no conversation to store. The run starts, the events arrive, the run ends. The
handoff project in this series cannot do that -- there an agent may stop and ask
the user, so it has to keep the suspended workflow alive between turns.
"""

import asyncio
import sys

from dotenv import load_dotenv

from orchestrations import sequential as orchestration
from services.foundry import ConfigurationError, FoundryService

REQUEST = "I live in a small apartment and want a quiet pet."


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


async def main() -> None:
    load_dotenv()
    request = sys.argv[1] if len(sys.argv) > 1 else REQUEST
    foundry = FoundryService()
    workflow = await orchestration.build(foundry)
    print(f"[You]\n{request}", flush=True)

    try:
        # One pass. Each agent speaks once, in the order the builder fixed.
        speaker = None
        async for event in workflow.run(request, stream=True):
            speaker = show(event, speaker)
        print("\n\n-- done --")
    finally:
        # Deletes the CSVs uploaded to Foundry for this run.
        await foundry.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigurationError as error:
        raise SystemExit(f"{error}\nCopy .env.example to .env, then run: az login")
    except KeyboardInterrupt:
        print()
