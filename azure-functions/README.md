# Handoff on Azure Functions

The dealership handoff agent from `agent-academy-handoff`, deployed as a
serverless function app instead of a terminal program.

The pattern does not change. What changes is **who drives the loop** and **where
the paused conversation lives**.

## Why this pattern wants serverless

A handoff workflow stops and waits for a person, for an unbounded time. In the
CLI, the paused run was a Python object held in your terminal. On a server, that
object has to survive between two HTTP requests — and survive a deploy, and be
reachable from whichever instance handles the next request.

Durable Functions solves exactly that, and the economics match:

> orchestrations can wait for days or even weeks … all compute resources are
> spun down during the wait period, eliminating compute costs until the human
> provides their input

A customer who wanders off mid-conversation costs you nothing.

## The same loop, two transports

```
CLI (agent-academy-handoff)            Azure Functions
-------------------------------------  ----------------------------------------------
workflow.run(OPENING)                  POST /workflow/dealership_handoff/run
request = await collect(...)           GET  /workflow/dealership_handoff/status/{instanceId}
responses={request.request_id: reply}  POST /workflow/dealership_handoff/respond/{instanceId}/{requestId}
while request is not None               while the status reports pending requests
terminate() -> []                      POST the same respond route with an empty body
```

`{requestId}` is not a new concept. The package says so itself:

> The requestId in the URL corresponds to the `request_id` from the
> `RequestInfoEvent`.

It is the same key the CLI used in `responses={request.request_id: answer}`.
`{instanceId}` is the conversation — the durable orchestration that holds the
suspended run.

## What actually changed in the code

Only two things, and both are consequences of the host, not the pattern:

| | CLI | here |
| --- | --- | --- |
| building the workflow | `await build(foundry)` — it owned its event loop | **synchronous** `create_workflow()`; the host imports this module and wants a finished graph |
| the CSVs | uploaded on every start | uploaded **once** by `upload_data.py`; ids arrive as app settings |

The agents, their instructions and the handoff rules are copied over unchanged.

`function_app.py` is the whole integration:

```python
from agent_framework_azurefunctions import AgentFunctionApp
from dealership import create_workflow

app = AgentFunctionApp(workflow=create_workflow(), enable_health_check=True)
```

That one line generates 13 functions — an HTTP and a durable entry per agent,
the orchestrator, and the three routes above.

## Configure

1. **Upload the data once** and note the two ids it prints:

   ```bash
   export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
   export FOUNDRY_MODEL="gpt-4o"
   az login
   python upload_data.py
   ```

2. **Local settings** — copy the sample and fill it in:

   ```bash
   cp local.settings.json.sample local.settings.json
   ```

   You need a **Durable Task Scheduler** connection string. That is where paused
   conversations live; without it there is nothing to resume from.

## Run it locally

```bash
func start          # requires azure-functions-core-tools@4
python talk.py      # in another terminal
```

`talk.py` is the CLI conversation loop written against HTTP. Type `quit` at any
prompt to end the conversation with an empty response — the same `terminate()`
trick, over the wire.

## Deploy

```bash
az functionapp create \
  --resource-group <rg> --name <app> \
  --flexconsumption-location <region> \
  --runtime python --runtime-version 3.12 \
  --storage-account <storage>

az functionapp config appsettings set --name <app> --resource-group <rg> --settings \
  FOUNDRY_PROJECT_ENDPOINT="..." FOUNDRY_MODEL="gpt-4o" \
  VEHICLES_FILE_ID="..." LOAN_OPTIONS_FILE_ID="..." \
  DURABLE_TASK_SCHEDULER_CONNECTION_STRING="..."

func azure functionapp publish <app>
```

Use **Flex Consumption** — that is the plan that scales to zero, which is the
entire point for a workflow that waits on people.

Then give the app a **managed identity** and grant it access to your Foundry
project. `dealership.py` picks `ManagedIdentityCredential` automatically when
`AZURE_CLIENT_ID` is set, and falls back to your `az login` locally.

```bash
python talk.py https://<app>.azurewebsites.net/api <function-key>
```

## Two things that will bite you

**Pin `agent-framework-orchestrations`.** Version 1.3.2 added a requirement that
1.3.1 did not have: every participant in a handoff workflow needs
`require_per_service_call_history_persistence=True`. Build with 1.3.1 and
upgrade, and you get a `ValueError` at start-up naming every agent.

**Keep the workflow name and executor ids stable.** Checkpoint restore matches on
identity. Rename an agent between deploys and in-flight conversations cannot be
resumed — they do not error loudly, they simply fail to match.

## Status of these packages

`agent-framework-azurefunctions` and `agent-framework-durabletask` are
**prerelease** (`--pre`). The underlying Durable Task infrastructure is long
established; it is the Agent Framework binding that is young. Pin versions and
expect API movement.
