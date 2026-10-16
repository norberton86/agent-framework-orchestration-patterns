"""Hold a conversation with the deployed workflow. The CLI loop, over HTTP.

    python talk.py                        # against a local `func start`
    python talk.py https://<app>.azurewebsites.net/api  <function-key>

Put the two side by side and the shape is identical:

    CLI                                   HTTP
    ------------------------------------  --------------------------------------
    workflow.run(OPENING)                 POST /workflow/<name>/run
    request = await collect(...)          GET  /workflow/<name>/status/{instance}
    responses={request.request_id: ...}   POST /workflow/<name>/respond/{instance}/{requestId}
    while request is not None             while there are pending requests

The difference is where the paused run lives. In the CLI it was a Python object
in your terminal. Here it is a durable orchestration -- so this script can be
closed and restarted mid-conversation, and the instance id still resumes it.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

WORKFLOW = "dealership_handoff"
OPENING = "I need a new family SUV"
QUIT = {"quit", "exit"}


def call(url: str, key: str | None, payload: dict | str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-functions-key"] = key
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"{err.code} {err.reason}\n{err.read().decode()[:400]}")
    return json.loads(body) if body.strip() else {}


def pending_of(status: dict) -> list[dict]:
    """Pending human-in-the-loop requests, whatever the host calls the field."""
    for field in ("pendingRequests", "pending_requests", "requests"):
        found = status.get(field)
        if isinstance(found, list) and found:
            return found
    return []


def main() -> None:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7071/api").rstrip("/")
    key = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"[You]\n{OPENING}\n", flush=True)
    started = call(f"{base}/workflow/{WORKFLOW}/run", key, OPENING)
    instance = started.get("instanceId") or started.get("id")
    if not instance:
        raise SystemExit(f"No instance id in the response:\n{json.dumps(started, indent=2)[:600]}")
    print(f"[instance] {instance}\n", flush=True)

    while True:
        # Poll until the run either finishes or parks on a question.
        while True:
            status = call(f"{base}/workflow/{WORKFLOW}/status/{instance}", key)
            runtime = (status.get("runtimeStatus") or status.get("status") or "").lower()
            waiting = pending_of(status)
            if waiting or runtime in {"completed", "failed", "terminated"}:
                break
            time.sleep(1)

        if not waiting:
            print(f"\n-- conversation {runtime or 'over'} --")
            output = status.get("output")
            if output:
                print(json.dumps(output, indent=2)[:1200])
            return

        # One pause at a time in plain handoff -- the same invariant as the CLI.
        request = waiting[0]
        request_id = request.get("requestId") or request.get("request_id") or request.get("id")
        prompt = request.get("prompt") or request.get("data") or ""
        print(f"\n? {prompt if isinstance(prompt, str) else json.dumps(prompt)[:400]}\n", flush=True)

        reply = input("You: ").strip()
        if reply.lower() in QUIT:
            # terminate() is an empty message list -- the same trick, over HTTP.
            call(f"{base}/workflow/{WORKFLOW}/respond/{instance}/{request_id}", key, [])
            print("\n-- ended --")
            return
        call(f"{base}/workflow/{WORKFLOW}/respond/{instance}/{request_id}", key, reply)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
