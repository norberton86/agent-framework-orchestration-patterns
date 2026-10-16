"""Azure Functions entry point. This file is the entire integration.

`AgentFunctionApp` takes the finished workflow and generates the HTTP surface
and the durable orchestration around it. Compare the CLI project: there *you*
wrote the loop that ran the workflow, caught the pause and fed the answer back.
Here the platform does it, and persists the paused run in between.

    POST /api/workflow/dealership_handoff/run
    GET  /api/workflow/dealership_handoff/status/{instanceId}
    POST /api/workflow/dealership_handoff/respond/{instanceId}/{requestId}
    GET  /api/health

`{requestId}` in that third route is the same `request_id` the CLI used as the
key in `responses={request.request_id: answer}`. The pause did not change; only
the transport did.
"""

from agent_framework_azurefunctions import AgentFunctionApp

from dealership import create_workflow

# Built once at import. Azure Functions reuses this module across invocations on
# the same worker, so keep this synchronous and side-effect free apart from the
# client construction itself.
app = AgentFunctionApp(workflow=create_workflow(), enable_health_check=True)
