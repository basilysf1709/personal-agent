from agent.tools.web_search import web_search, WEB_SEARCH_SCHEMA
from agent.tools.compile_latex import compile_latex, COMPILE_LATEX_SCHEMA
from agent.tools.run_command import run_command, RUN_COMMAND_SCHEMA
from agent.tools.apply_to_job import apply_to_job, APPLY_TO_JOB_SCHEMA
from agent.tools.update_resume import update_resume, UPDATE_RESUME_SCHEMA

# Tool registry: maps tool name -> {function, schema}
# To add a new tool, import it and add an entry here.
TOOLS = {
    "web_search": {
        "function": web_search,
        "schema": WEB_SEARCH_SCHEMA,
    },
    "compile_latex": {
        "function": compile_latex,
        "schema": COMPILE_LATEX_SCHEMA,
    },
    "run_command": {
        "function": run_command,
        "schema": RUN_COMMAND_SCHEMA,
    },
    "apply_to_job": {
        "function": apply_to_job,
        "schema": APPLY_TO_JOB_SCHEMA,
    },
    "update_resume": {
        "function": update_resume,
        "schema": UPDATE_RESUME_SCHEMA,
    },
}


def get_tool_schemas():
    """Return list of tool schemas for the Claude API."""
    return [tool["schema"] for tool in TOOLS.values()]


def run_tool(name: str, input: dict) -> str:
    """Execute a tool by name with the given input. Returns result as string."""
    if name not in TOOLS:
        return f"Error: Unknown tool '{name}'"
    try:
        return TOOLS[name]["function"](**input)
    except Exception as e:
        return f"Error running {name}: {e}"
