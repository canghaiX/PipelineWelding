from __future__ import annotations

import argparse
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


load_dotenv()

mcp = FastMCP("pipeline-welding-external-search")


@mcp.tool()
def search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search external web data through Tavily."""
    return {"results": _search_tavily(query, max_results)}


def _search_tavily(query: str, max_results: int) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return [{"title": "TAVILY_API_KEY is missing", "url": "", "snippet": ""}]

    response = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "score": item.get("score"),
            "source": "tavily",
        }
        for item in data.get("results", [])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline welding external search MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport. Use stdio for local subprocess mode.",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
