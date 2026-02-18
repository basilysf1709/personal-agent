from duckduckgo_search import DDGS

WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": "Search the web using DuckDuckGo. Use this to find current information, news, facts, or anything that requires up-to-date knowledge.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return formatted results."""
    results = DDGS().text(query, max_results=max_results)

    if not results:
        return "No results found."

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(f"{i}. {r['title']}\n   {r['href']}\n   {r['body']}")

    return "\n\n".join(formatted)
