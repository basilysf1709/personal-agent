import subprocess

RUN_COMMAND_SCHEMA = {
    "name": "run_command",
    "description": "Execute a shell command on the server and return the output. Use this for running scripts, checking system info, installing packages, running Python code, file operations, etc.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
        },
        "required": ["command"],
    },
}

TIMEOUT = 30


def run_command(command: str) -> str:
    """Execute a shell command and return stdout + stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output:
            output = f"(no output, exit code {result.returncode})"
        # Truncate long output
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"
        return output
    except subprocess.TimeoutExpired:
        return f"Command timed out after {TIMEOUT}s"
    except Exception as e:
        return f"Error: {e}"
