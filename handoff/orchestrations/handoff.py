"""Interactive dealership conversation with explicit handoff edges."""

from __future__ import annotations

from typing import Any


async def build(foundry: Any) -> Any:
    from agent_framework.foundry import FoundryChatClient
    from agent_framework.orchestrations import HandoffBuilder

    await foundry.ensure_ready()
    reception = foundry.client.as_agent(
        name="ReceptionAgent",
        description="Routes dealership customers to new or used vehicle specialists.",
        instructions=(
            "You are dealership reception. Hand off clear new-car requests to NewCarSpecialist and "
            "clear used-car requests to UsedCarSpecialist. For ambiguous requests, ask one focused "
            "question. Do not claim a handoff unless you call its handoff tool."
        ),
    )
    new = foundry.client.as_agent(
        name="NewCarSpecialist",
        description="Discusses new vehicles and customer requirements.",
        instructions=(
            "Discuss new vehicles. Ask about budget and requirements when needed. Use Code Interpreter "
            "with vehicles.csv to mention only listings with condition New. Hand off financing requests "
            "to FinancingSpecialist; route unrelated requests to ReceptionAgent."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("vehicles.csv")
        )],
    )
    used = foundry.client.as_agent(
        name="UsedCarSpecialist",
        description="Discusses used vehicles and customer requirements.",
        instructions=(
            "Discuss used vehicles. Ask about budget and requirements when needed. Use Code Interpreter "
            "with vehicles.csv to mention only listings with condition Used. Hand off financing requests "
            "to FinancingSpecialist; route unrelated requests to ReceptionAgent."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("vehicles.csv")
        )],
    )
    finance = foundry.client.as_agent(
        name="FinancingSpecialist",
        description="Calculates fictional payment examples from the supplied CSVs.",
        instructions=(
            "Use Code Interpreter to read vehicles.csv and loan_options.csv. Ask for missing selected "
            "vehicle, down payment or term. Calculate an illustrative monthly amortized payment from "
            "CSV price and annual rate, stating inputs and assumptions. This is a fictional tutorial, "
            "not financial advice or a credit decision. Return to ReceptionAgent when done."
        ),
        tools=[FoundryChatClient.get_code_interpreter_tool(
            file_ids=await foundry.upload_csvs("vehicles.csv", "loan_options.csv")
        )],
    )
    return (
        HandoffBuilder(
            name="dealership_handoff",
            participants=[reception, new, used, finance],
        )
        .with_start_agent(reception)
        .add_handoff(reception, [new, used])
        .add_handoff(new, [finance, reception])
        .add_handoff(used, [finance, reception])
        .add_handoff(finance, [reception])
        .enable_return_to_previous(True)
        .build()
    )
