import anthropic
from agent.tools import get_tool_schemas, run_tool

SYSTEM_PROMPT = """You are a helpful personal assistant connected via WhatsApp. Be concise and conversational — this is a chat app, not an essay.

You have access to tools when needed. Use web_search for current events, facts, or anything requiring up-to-date information.

Keep responses short and mobile-friendly unless the user asks for detail."""

MODEL = "claude-sonnet-4-5-20241022"
MAX_TOOL_ROUNDS = 10


def run_agent(user_message: str, conversation_history: list | None = None) -> str:
    """Run the Claude agent loop. Returns the final text response."""
    client = anthropic.Anthropic()
    tools = get_tool_schemas()

    messages = conversation_history or []
    messages.append({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        # Collect text and tool_use blocks
        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # If no tool calls, we're done
        if response.stop_reason == "end_turn" or not tool_uses:
            return "\n".join(text_parts) if text_parts else "I couldn't generate a response."

        # Append assistant message with all content blocks
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool and collect results
        tool_results = []
        for tool_use in tool_uses:
            result = run_tool(tool_use.name, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Exhausted tool rounds, return whatever text we have
    return "\n".join(text_parts) if text_parts else "I used too many tool calls. Please try a simpler question."
