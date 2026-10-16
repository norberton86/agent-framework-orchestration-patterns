"""A pipeline: each participant sees the preceding conversation."""

from __future__ import annotations

from typing import Any


async def build(foundry: Any) -> Any:
    from agent_framework.foundry import FoundryChatClient
    from agent_framework.orchestrations import SequentialBuilder

    await foundry.ensure_ready()
    pets_tool = FoundryChatClient.get_code_interpreter_tool(
        file_ids=await foundry.upload_csvs("pets.csv")
    )
    receptionist = foundry.client.as_agent(
        name="PetReceptionist",
        instructions="Extract the customer's pet preferences into a short, structured list. Do not recommend a pet yet.",
    )
    expert = foundry.client.as_agent(
        name="PetExpert",
        instructions=(
            "Use Code Interpreter to read the attached pets.csv. Rank real rows against the customer's "
            "preferences, cite each candidate's CSV attributes, and never invent a pet or attribute."
        ),
        tools=[pets_tool],
    )
    advisor = foundry.client.as_agent(
        name="AdoptionAdvisor",
        instructions="Review the PetExpert ranking and recommend one available pet with a concise reason.",
    )
    return SequentialBuilder(
        participants=[receptionist, expert, advisor],
        intermediate_output_from=[receptionist, expert],
    ).build()
