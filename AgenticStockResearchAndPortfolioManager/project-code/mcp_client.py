"""Synchronous MCP client. Starts one MCP server as a child process (stdio) and keeps it for the whole session.

Agents use this to find the tools a server offers and to call them. The MCP session lives on its own event
loop in a background thread, so agent code stays plain synchronous Python.

    with McpServer("market-data", "mcp_market_data.py") as server:
        server.openai_tools()                       # tool list in the neutral format the gateway expects
        server.call("get_latest_quote", {"symbol": "TCS"})   # -> str (JSON text from the server)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config

START_TIMEOUT_S = 60
CALL_TIMEOUT_S = 60


class McpClientError(RuntimeError):
    pass


class McpServer:
    def __init__(self, name: str, script: str):
        self.name = name
        self.script = Path(config.get("code_dir")) / script
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name=f"mcp-{name}", daemon=True)
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: list = []

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> "McpServer":
        self._thread.start()
        try:
            self._submit(self._connect(), START_TIMEOUT_S)
        except Exception as exc:
            self.close()
            raise McpClientError(f"could not start MCP server '{self.name}': {exc}") from exc
        return self

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._submit(self._stack.aclose(), 15)
            except Exception:
                pass
            self._stack = None
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    def __enter__(self) -> "McpServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- tools
    def tool_names(self) -> list[str]:
        return [t.name for t in self._tools]

    def openai_tools(self, only: list[str] | None = None) -> list[dict]:
        """Tool list in the neutral format the gateway and providers use."""
        return [{"type": "function",
                 "function": {"name": t.name, "description": (t.description or "").strip(),
                              "parameters": t.input_schema or {"type": "object", "properties": {}}}}
                for t in self._tools if only is None or t.name in only]

    def call(self, tool: str, arguments: dict | None = None) -> str:
        if tool not in self.tool_names():
            raise McpClientError(f"MCP server '{self.name}' has no tool '{tool}'")
        try:
            result = self._submit(self._session.call_tool(tool, arguments or {}), CALL_TIMEOUT_S)
        except Exception as exc:
            raise McpClientError(f"{self.name}.{tool} failed: {exc}") from exc
        text = "\n".join(getattr(block, "text", "") for block in (result.content or []))
        if result.is_error:
            return json.dumps({"error": text or "tool failed"})
        return text

    # ---------------------------------------------------------------- internals
    async def _connect(self) -> None:
        self._stack = AsyncExitStack()
        # The SDK passes only a few safe variables by default. A server that searches documents must embed the question
        # through the gateway, so it needs OLLAMA_HOST and any API key variable the settings name.
        params = StdioServerParameters(command=sys.executable, args=[str(self.script)], cwd=str(self.script.parent),
                                       env=dict(os.environ))
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listing = await self._session.list_tools()
        self._tools = list(getattr(listing, "tools", listing))

    def _submit(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)
