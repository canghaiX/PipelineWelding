from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Literal


Transport = Literal["stdio", "streamable_http"]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str = ""
    snippet: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class McpSearchConfig:
    transport: Transport = "stdio"
    tool_name: str = "search"
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    max_results: int = 5


class McpSearchClient:
    """Minimal MCP client wrapper for a search tool exposed by an MCP server."""

    def __init__(self, config: McpSearchConfig) -> None:
        self.config = config

    async def search(self, query: str) -> list[SearchResult]:
        if self.config.transport == "stdio":
            return await self._search_stdio(query)
        if self.config.transport == "streamable_http":
            return await self._search_streamable_http(query)
        raise ValueError(f"Unsupported MCP transport: {self.config.transport}")

    async def _search_stdio(self, query: str) -> list[SearchResult]:
        if not self.config.command:
            return []

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=self.config.env or None,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tool_name = await self._resolve_tool_name(session)
                result = await session.call_tool(
                    tool_name,
                    arguments={"query": query, "max_results": self.config.max_results},
                )
                return self._parse_tool_result(result)

    async def _search_streamable_http(self, query: str) -> list[SearchResult]:
        if not self.config.url:
            return []

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(self.config.url) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tool_name = await self._resolve_tool_name(session)
                result = await session.call_tool(
                    tool_name,
                    arguments={"query": query, "max_results": self.config.max_results},
                )
                return self._parse_tool_result(result)

    async def _resolve_tool_name(self, session: Any) -> str:
        try:
            tools_result = await session.list_tools()
        except Exception:
            return self.config.tool_name

        tools = getattr(tools_result, "tools", []) or []
        tool_names = [getattr(tool, "name", "") for tool in tools]
        if self.config.tool_name in tool_names:
            return self.config.tool_name

        normalized_config_name = self.config.tool_name.replace("-", "_")
        for name in tool_names:
            if name.replace("-", "_") == normalized_config_name:
                return name

        for name in tool_names:
            if "search" in name.lower():
                return name

        return self.config.tool_name

    @staticmethod
    def _parse_tool_result(result: Any) -> list[SearchResult]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            items = structured.get("results") or structured.get("items") or []
            if isinstance(items, list):
                return [McpSearchClient._result_from_dict(item) for item in items]

        parsed_results = []
        for content in getattr(result, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    parsed_results.append(SearchResult(title=text[:80], snippet=text, raw={"text": text}))
                    continue

                items = data.get("results") if isinstance(data, dict) else None
                if isinstance(items, list):
                    parsed_results.extend(McpSearchClient._result_from_dict(item) for item in items)
                else:
                    parsed_results.append(McpSearchClient._result_from_dict(data))
        return parsed_results

    @staticmethod
    def _result_from_dict(item: Any) -> SearchResult:
        if not isinstance(item, dict):
            return SearchResult(title=str(item), snippet=str(item), raw={"value": item})
        return SearchResult(
            title=str(item.get("title") or item.get("name") or item.get("url") or "search_result"),
            url=str(item.get("url") or item.get("link") or ""),
            snippet=str(item.get("snippet") or item.get("summary") or item.get("content") or ""),
            raw=item,
        )
