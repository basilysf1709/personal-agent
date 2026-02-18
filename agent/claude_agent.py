import json
import anthropic
from agent.tools import get_tool_schemas, run_tool

SYSTEM_PROMPT = """You are a helpful personal assistant connected via WhatsApp. Be concise and conversational — this is a chat app, not an essay.

You have access to tools when needed:
- web_search: for current events, facts, or anything requiring up-to-date information
- compile_latex: for generating PDF documents. When asked to create a document, resume, paper, letter, cheat sheet, etc., write complete LaTeX and use this tool to compile it.

Keep responses short and mobile-friendly unless the user asks for detail."""

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOOL_ROUNDS = 10


def run_agent(user_message: str, conversation_history: list | None = None) -> dict:
    """Run the Claude agent loop. Returns dict with 'text' and optional 'file'."""
    client = anthropic.Anthropic()
    tools = get_tool_schemas()

    messages = conversation_history or []
    messages.append({"role": "user", "content": user_message})

    file_attachment = None

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
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
            text = "\n".join(text_parts) if text_parts else "I couldn't generate a response."
            result = {"text": text}
            if file_attachment:
                result["file"] = file_attachment
            return result

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

            # Check if compile_latex returned a PDF
            if tool_use.name == "compile_latex":
                try:
                    parsed = json.loads(result)
                    if parsed.get("success") and parsed.get("pdf_base64"):
                        file_attachment = {
                            "base64": parsed["pdf_base64"],
                            "filename": parsed.get("filename", "document.pdf"),
                            "mimetype": "application/pdf",
                        }
                except (json.JSONDecodeError, KeyError):
                    pass

        messages.append({"role": "user", "content": tool_results})

    text = "\n".join(text_parts) if text_parts else "I used too many tool calls. Please try a simpler question."
    result = {"text": text}
    if file_attachment:
        result["file"] = file_attachment
    return result
