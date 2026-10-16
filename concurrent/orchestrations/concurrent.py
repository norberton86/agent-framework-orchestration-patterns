"""Independent specialists process the same order in parallel."""

from __future__ import annotations

from typing import Any


async def build(foundry: Any) -> Any:
    from agent_framework.foundry import FoundryChatClient
    from agent_framework.orchestrations import ConcurrentBuilder

    await foundry.ensure_ready()
    inventory = foundry.client.as_agent(
        name="InventoryAgent",
        instructions=(
            "Use Code Interpreter to read bakery_inventory.csv. Check every requested item and quantity "
            "against available_quantity. Never invent stock."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("bakery_inventory.csv")
        )],
    )
    pricing = foundry.client.as_agent(
        name="PricingAgent",
        instructions=(
            "Use Code Interpreter to read bakery_inventory.csv. Calculate every requested subtotal and "
            "the grand total using only CSV unit_price values. Show arithmetic and USD formatting."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("bakery_inventory.csv")
        )],
    )
    delivery = foundry.client.as_agent(
        name="DeliveryAgent",
        instructions=(
            "Use Code Interpreter to read bakery_inventory.csv. Multiply each requested quantity by "
            "that item's prep_minutes_per_unit, sum the results, and report the total in hours and "
            "minutes. Show the per-item arithmetic. Use only CSV values; never invent a prep time. "
            "State clearly that this is a demo estimate, not a live delivery promise. Do not comment "
            "on stock levels or prices -- other agents cover those."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("bakery_inventory.csv")
        )],
    )
    return ConcurrentBuilder(
        participants=[inventory, pricing, delivery],
        intermediate_output_from=[inventory, pricing, delivery],
    ).build()
