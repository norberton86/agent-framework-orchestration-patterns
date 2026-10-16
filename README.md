# Microsoft Agent Framework — Orchestration Patterns

Five standalone projects, one per tutorial video. Each runs on its own, shares no
code with the others, and demonstrates exactly one idea.

| | project | what it shows |
| --- | --- | --- |
| 01 | [`sequential/`](sequential) | A pipeline — each agent receives everything the previous one produced |
| 02 | [`concurrent/`](concurrent) | Three agents answer the same request at once and never see each other's work |
| 03 | [`handoff/`](handoff) | Agents transfer ownership of a conversation — and the workflow pauses for you |
| 04 | [`handoff-approval/`](handoff-approval) | The same, plus a tool that cannot run until a human approves it |
| 05 | [`azure-functions/`](azure-functions) | Project 03 deployed to Azure Functions — same pattern, different host |

## The distinction the series turns on

**01 and 02 run start to finish.** An agent's response has exactly one place to
go next, so the workflow always knows its own next step and a run completes in
one pass. There is nowhere to pause.

**03 and 04 stop and wait for you.** A handoff agent has a *choice*: transfer to
a specialist, or keep serving the customer itself. Transfers happen through a
tool call, so when an agent writes a reply **instead of** calling a handoff
tool, the workflow has no next edge to follow and hands control back to you.
That pause is a `request_info` event, and the run stays suspended until it is
answered by `request_id`.

That is why 01 and 02 are about 30 lines of driving code, and 03 and 04 need a
loop.

## Running any of them

Each project is independent — its own venv, its own dependencies:

```bash
cd handoff          # or sequential, concurrent, handoff-approval
cp .env.example .env    # set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL
az login
./run-local.sh
```

`run-local.sh` creates the venv, installs, runs the tests, then runs `main.py`.
Every project also takes a request on the command line:

```bash
.venv/bin/python main.py "I want a low-energy pet"
```

`azure-functions/` deploys rather than runs locally — see
[its README](azure-functions/README.md).

## Where the lesson lives

In 01–04, `main.py` *is* the lesson. It is short on purpose:

| project | `main.py` | the pattern |
| --- | --- | --- |
| sequential | 32 lines of code | 36 lines |
| concurrent | 32 | 44 |
| handoff | 54 | 72 |
| handoff-approval | 78 | 68 |

Everything else — `orchestrations/` for the agents and rules, `services/foundry.py`
for the client and CSV uploads, `data/` for what the agents read — is supporting
cast.

## Tests

```bash
cd <project> && .venv/bin/python -m pytest -q
```

Tests drive `main.py` with a fake workflow and scripted keystrokes, so the
pause/answer loop is exercised without contacting Azure or spending model
credits. They do not prove Foundry execution; for that, configure `.env` and run
it for real.

## Prerequisites

- Python 3.12
- A [Microsoft Foundry](https://learn.microsoft.com/azure/ai-foundry/) project
  with a model deployment
- Azure CLI, signed in with `az login`

## A note on versions

These use prerelease packages and at least one breaking change has already landed
in a patch release: `agent-framework-orchestrations` **1.3.2** requires every
handoff participant to set `require_per_service_call_history_persistence=True`,
which **1.3.1** did not. Pin your versions.

---

The dealership financing example is a simulation. It makes no credit decision and
sends no transaction. Pet, bakery and vehicle data are fictional.
