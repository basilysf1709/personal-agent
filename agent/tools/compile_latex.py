import os
import json
import base64
import httpx

COMPILE_URL = os.environ.get("COMPILE_URL", "https://compile.useoctree.com")
COMPILE_JWT = os.environ.get("COMPILE_JWT_TOKEN", "")

COMPILE_LATEX_SCHEMA = {
    "name": "compile_latex",
    "description": "Compile LaTeX source code into a PDF document. Use this when the user asks you to create, generate, or compile a document, resume, paper, letter, cheat sheet, or any formatted PDF. You must provide complete, valid LaTeX source code.",
    "input_schema": {
        "type": "object",
        "properties": {
            "latex_content": {
                "type": "string",
                "description": "Complete LaTeX source code starting with \\documentclass",
            },
            "filename": {
                "type": "string",
                "description": "Name for the output PDF (without .pdf extension)",
                "default": "document",
            },
        },
        "required": ["latex_content"],
    },
}


def compile_latex(latex_content: str, filename: str = "document") -> str:
    """Compile LaTeX to PDF via octree-compile service."""
    headers = {"Content-Type": "application/json"}
    if COMPILE_JWT:
        headers["Authorization"] = f"Bearer {COMPILE_JWT}"

    payload = {
        "files": [{"path": "main.tex", "content": latex_content}],
        "projectId": f"wa-{filename}",
    }

    response = httpx.post(
        f"{COMPILE_URL}/compile",
        json=payload,
        headers=headers,
        timeout=60.0,
    )

    if response.status_code == 200:
        pdf_base64 = base64.b64encode(response.content).decode()
        return json.dumps({
            "success": True,
            "pdf_base64": pdf_base64,
            "filename": f"{filename}.pdf",
        })
    else:
        try:
            error = response.json()
            return json.dumps({
                "success": False,
                "error": error.get("message", "Compilation failed"),
                "log": error.get("log", "")[:500],
            })
        except Exception:
            return json.dumps({
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
            })
