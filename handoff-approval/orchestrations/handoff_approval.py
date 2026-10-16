"""A handoff that gates a simulated financing record behind human approval."""

from __future__ import annotations

import math
from typing import Any


async def build(foundry: Any, tool_state: dict[str, Any]) -> Any:
    from agent_framework import tool
    from agent_framework.foundry import FoundryChatClient
    from agent_framework.orchestrations import HandoffBuilder

    await foundry.ensure_ready()

    @tool(approval_mode="always_require")
    def approve_vehicle_financing(customer_name: str, vehicle: str, amount: float) -> str:
        """Simulate recording a financing approval; no credit decision or external transaction."""
        if not customer_name.strip() or not vehicle.strip() or not math.isfinite(amount) or amount <= 0:
            raise ValueError("A customer, vehicle and positive finite amount are required.")
        tool_state["executed"] = True
        tool_state["record"] = {"customer_name": customer_name, "vehicle": vehicle, "amount": amount}
        return f"Tutorial simulation recorded for {customer_name}: {vehicle}, ${amount:,.2f}."

    reception = foundry.client.as_agent(
        name="ReceptionAgent",
        description="Routes new-car customers to a specialist.",
        instructions="Route the customer to NewCarSpecialist using the handoff tool.",
    )
    new = foundry.client.as_agent(
        name="NewCarSpecialist",
        description="Helps select a sample new vehicle.",
        instructions=(
            "Help select a New vehicle from vehicles.csv using Code Interpreter. Ask for a name, "
            "vehicle and down payment as needed. Route financing requests to FinancingSpecialist."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("vehicles.csv")
        )],
    )
    finance = foundry.client.as_agent(
        name="FinancingSpecialist",
        description="Calculates examples and requests a human-reviewed simulated financing record.",
        instructions=(
            "Use Code Interpreter with vehicles.csv and loan_options.csv to calculate an illustrative "
            "monthly payment. Ask for missing customer name, sample vehicle, down payment or loan term. "
            "After the customer explicitly selects a vehicle and you calculate the example, call "
            "approve_vehicle_financing with the customer name, exact CSV vehicle and financed amount "
            "(price minus down payment). The tool requires human approval. Never claim it executed "
            "before its result arrives. This is only a tutorial simulation, not a credit decision."
        ),
        tools=[
            FoundryChatClient.get_code_interpreter_tool(
                file_ids=await foundry.upload_csvs("vehicles.csv", "loan_options.csv")
            ),
            approve_vehicle_financing,
        ],
    )
    return (
        HandoffBuilder(name="financing_approval", participants=[reception, new, finance])
        .with_start_agent(reception)
        .add_handoff(reception, [new])
        .add_handoff(new, [finance, reception])
        .add_handoff(finance, [reception])
        .enable_return_to_previous(True)
        .build()
    )
