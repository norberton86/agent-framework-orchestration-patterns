"""The same dealership agents as the CLI project, built for a serverless host.

Only two things differ from `agent-academy-handoff/orchestrations/handoff.py`,
and both are consequences of *where* this runs, not of the pattern:

1. The workflow is built **synchronously**. Azure Functions imports this module
   once at start-up and `AgentFunctionApp(workflow=...)` wants a finished graph,
   so there is nowhere to `await` anything. The CLI could `await build(foundry)`
   because it owned its own event loop.

2. The CSVs are uploaded **once at deploy time**, not on every start. Uploading
   is async, so it cannot happen here -- and re-uploading on every cold start
   would be wasteful anyway. `upload_data.py` does it and prints the file ids;
   they arrive here as app settings.

The agents, their instructions and the handoff rules are unchanged.
"""

from __future__ import annotations

import os

from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import HandoffBuilder
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential

WORKFLOW_NAME = "dealership_handoff"   # this becomes the URL: /api/workflow/<name>/run


def _credential():
    """Managed identity once deployed; your az login when running locally."""
    client_id = os.getenv("AZURE_CLIENT_ID")
    return ManagedIdentityCredential(client_id=client_id) if client_id else AzureCliCredential()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. See README 'Configure'.")
    return value


def _file_ids(*names: str) -> list[str]:
    """Foundry file ids produced by upload_data.py and stored as app settings."""
    return [_require(n) for n in names]


def create_workflow():
    """Build the handoff graph. Synchronous on purpose -- see the module docstring."""
    client = FoundryChatClient(
        project_endpoint=_require("FOUNDRY_PROJECT_ENDPOINT"),
        model=_require("FOUNDRY_MODEL"),
        credential=_credential(),
    )

    def agent(name: str, description: str, instructions: str, files: list[str] | None = None):
        tools = (
            [FoundryChatClient.get_code_interpreter_tool(file_ids=files)] if files else None
        )
        return client.as_agent(
            name=name,
            description=description,
            instructions=instructions,
            tools=tools,
            # Required by agent-framework-orchestrations >= 1.3.2 for handoff
            # workflows: keeps local history consistent with the service across
            # the handoff tool-call short-circuit.
            require_per_service_call_history_persistence=True,
        )

    vehicles = _file_ids("VEHICLES_FILE_ID")
    financing = _file_ids("VEHICLES_FILE_ID", "LOAN_OPTIONS_FILE_ID")

    reception = agent(
        "ReceptionAgent",
        "Routes dealership customers to new or used vehicle specialists.",
        "You are dealership reception. Hand off clear new-car requests to NewCarSpecialist and "
        "clear used-car requests to UsedCarSpecialist. For ambiguous requests, ask one focused "
        "question. Do not claim a handoff unless you call its handoff tool.",
    )
    new = agent(
        "NewCarSpecialist",
        "Discusses new vehicles and customer requirements.",
        "Discuss new vehicles. Ask about budget and requirements when needed. Use Code Interpreter "
        "with vehicles.csv to mention only listings with condition New. Hand off financing requests "
        "to FinancingSpecialist; route unrelated requests to ReceptionAgent.",
        vehicles,
    )
    used = agent(
        "UsedCarSpecialist",
        "Discusses used vehicles and customer requirements.",
        "Discuss used vehicles. Ask about budget and requirements when needed. Use Code Interpreter "
        "with vehicles.csv to mention only listings with condition Used. Hand off financing requests "
        "to FinancingSpecialist; route unrelated requests to ReceptionAgent.",
        vehicles,
    )
    finance = agent(
        "FinancingSpecialist",
        "Calculates fictional payment examples from the supplied CSVs.",
        "Use Code Interpreter to read vehicles.csv and loan_options.csv. Ask for missing selected "
        "vehicle, down payment or term. Calculate an illustrative monthly amortized payment from "
        "CSV price and annual rate, stating inputs and assumptions. This is a fictional tutorial, "
        "not financial advice or a credit decision. Return to ReceptionAgent when done.",
        financing,
    )

    return (
        HandoffBuilder(
            name=WORKFLOW_NAME,
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
