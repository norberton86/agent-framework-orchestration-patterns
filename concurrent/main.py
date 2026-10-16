"""The concurrent pattern, end to end, in a terminal.

Run it:  .venv/bin/python main.py  ["your request"]

`ConcurrentBuilder` fans the same request out to every agent at once and
collects the results. The branches never see each other's output -- inventory,
pricing and delivery are independent questions about one order.

All three read the *same* bakery_inventory.csv, but each uses a different
column: available_quantity, unit_price, prep_minutes_per_unit. Shared input,
separate concerns, no coordination -- that is what this pattern buys you. (The
file is uploaded once and the id reused, so three readers cost one upload.)

Their text can arrive interleaved, so the speaker label below may switch back
and forth; that interleaving *is* the parallelism.

Notice what is *absent*: there is no pause to handle, no request id to answer,
no conversation to store. The run starts, the events arrive, the run ends. The
handoff project in this series cannot do that -- there an agent may stop and ask
the user, so it has to keep the suspended workflow alive between turns.
"""

import asyncio
import sys

from dotenv import load_dotenv

from orchestrations import concurrent as orchestration
from services.foundry import ConfigurationError, FoundryService

REQUEST = "100 cupcakes, 50 croissants, 20 cakes"


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
        # One pass. All branches run at once; their events interleave as they arrive.
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
