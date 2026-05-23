from __future__ import annotations

from pathlib import Path
import argparse

from mcp.server.fastmcp import FastMCP

from pipeline_welding.documents import read_docx_text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REFERENCE_DOC = PROJECT_ROOT / "data" / "MHPWPS-062.docx"

mcp = FastMCP("pipeline-welding-local-search")


@mcp.tool()
def search(query: str, max_results: int = 5) -> dict:
    """Search local welding reference data and return matching snippets."""
    reference_text = _safe_read_reference()
    if not reference_text:
        return {"results": []}

    query_terms = [term for term in query.replace("/", " ").replace("+", " ").split() if term]
    snippets = _find_snippets(reference_text, query_terms, max_results)
    return {
        "results": [
            {
                "title": "MHPWPS-062 本地焊接工艺参考",
                "url": str(DEFAULT_REFERENCE_DOC),
                "snippet": snippet,
                "source": "local_docx",
            }
            for snippet in snippets
        ]
    }


def _safe_read_reference() -> str:
    try:
        return read_docx_text(DEFAULT_REFERENCE_DOC)
    except FileNotFoundError:
        return ""


def _find_snippets(text: str, query_terms: list[str], max_results: int) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    scored: list[tuple[int, str]] = []
    for paragraph in paragraphs:
        score = sum(1 for term in query_terms if term.lower() in paragraph.lower())
        if score:
            scored.append((score, paragraph))

    if not scored:
        return paragraphs[:max_results]

    ranked = sorted(scored, key=lambda item: item[0], reverse=True)
    return [paragraph for _, paragraph in ranked[:max_results]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline welding local MCP search server.")
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
