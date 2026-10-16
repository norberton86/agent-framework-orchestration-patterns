"""Foundry inference and hosted CSV assets, all initialized on the app runtime."""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
log = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    pass


class FoundryService:
    def __init__(self) -> None:
        self.endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        self.model = os.getenv("FOUNDRY_MODEL", "").strip()
        self.client: Any = None
        self.openai_client: Any = None
        self.file_ids: dict[str, str] = {}
        self._credential: Any = None

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.model)

    async def ensure_ready(self) -> None:
        if self.client is not None:
            return
        if not self.configured:
            raise ConfigurationError("Set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL in .env.")
        if "/api/projects/" not in self.endpoint:
            raise ConfigurationError("FOUNDRY_PROJECT_ENDPOINT must be a Foundry project endpoint.")

        # Create this client on the same event loop that runs all workflows.
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import AzureCliCredential

        self._credential = AzureCliCredential()
        self.client = FoundryChatClient(
            project_endpoint=self.endpoint,
            model=self.model,
            credential=self._credential,
        )
        # The framework's own Foundry project client supplies the Files API for
        # the same project and authentication context as inference.
        self.openai_client = self.client.project_client.get_openai_client()

    async def _upload_file(self, filename: str) -> str:
        """Upload through the project's OpenAI-compatible Files API."""
        path = DATA_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Missing demo data file: {filename}")
        with path.open("rb") as handle:
            uploaded = await self.openai_client.files.create(file=handle, purpose="assistants")
        return uploaded.id

    async def upload_csvs(self, *filenames: str) -> list[str]:
        """Return Foundry file IDs for local CSVs used by native Code Interpreter."""
        await self.ensure_ready()
        import asyncio

        if not hasattr(self, "_upload_lock"):
            self._upload_lock = asyncio.Lock()
        async with self._upload_lock:
            for filename in filenames:
                if filename not in self.file_ids:
                    self.file_ids[filename] = await self._upload_file(filename)
        return [self.file_ids[name] for name in filenames]

    async def close(self) -> None:
        if self.openai_client is not None:
            for file_id in self.file_ids.values():
                try:
                    await self.openai_client.files.delete(file_id)
                except Exception as error:
                    log.error("Could not delete a demo CSV upload (%s)", type(error).__name__)
            close = getattr(self.openai_client, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
        if self._credential is not None:
            close = getattr(self._credential, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
