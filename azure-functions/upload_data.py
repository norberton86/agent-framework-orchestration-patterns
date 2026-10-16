"""Upload the demo CSVs to Foundry once, and print the ids to configure.

Run this before the first deploy, and again only if the CSVs change. Uploading
is async, which is exactly why it cannot live in `dealership.py` -- that module
is imported synchronously by the Functions host.

    python upload_data.py

Then set the two ids it prints as app settings (or in local.settings.json).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential

DATA = Path(__file__).parent / "data"
FILES = {"VEHICLES_FILE_ID": "vehicles.csv", "LOAN_OPTIONS_FILE_ID": "loan_options.csv"}


async def main() -> None:
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ.get("FOUNDRY_MODEL", "gpt-4o")
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=AzureCliCredential())
    files = client.project_client.get_openai_client().files

    print("Uploading. Set these as app settings:\n")
    for setting, filename in FILES.items():
        path = DATA / filename
        if not path.is_file():
            raise SystemExit(f"Missing {path}")
        with path.open("rb") as handle:
            uploaded = await files.create(file=handle, purpose="assistants")
        print(f"  {setting}={uploaded.id}")

    print("\n  az functionapp config appsettings set \\")
    print("     --name <app> --resource-group <rg> \\")
    print("     --settings VEHICLES_FILE_ID=... LOAN_OPTIONS_FILE_ID=...")


if __name__ == "__main__":
    asyncio.run(main())
