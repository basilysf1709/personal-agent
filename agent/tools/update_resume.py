import base64
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

RESUME_PATH = "/app/data/resume.pdf"

UPDATE_RESUME_SCHEMA = {
    "name": "update_resume",
    "description": (
        "Update the stored resume with a new PDF file sent as an attachment. "
        "Call this tool when the user sends a PDF attachment and asks to update/replace their resume. "
        "The attachment_base64 parameter should be the base64-encoded PDF data from the user's attachment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "attachment_base64": {
                "type": "string",
                "description": "Base64-encoded PDF file data from the user's attachment",
            },
        },
        "required": ["attachment_base64"],
    },
}


def update_resume(attachment_base64: str) -> str:
    """Save a base64-encoded PDF as the new resume."""
    try:
        pdf_bytes = base64.b64decode(attachment_base64)
    except Exception as e:
        return f"Error: Invalid base64 data — {e}"

    # Basic PDF validation
    if not pdf_bytes[:5] == b"%PDF-":
        return "Error: The attachment does not appear to be a valid PDF file."

    os.makedirs(os.path.dirname(RESUME_PATH), exist_ok=True)
    with open(RESUME_PATH, "wb") as f:
        f.write(pdf_bytes)

    size_kb = len(pdf_bytes) / 1024

    # Try to extract text to confirm it's readable
    page_info = ""
    try:
        result = subprocess.run(
            ["pdftotext", RESUME_PATH, "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            page_info = f" Extracted {len(lines)} lines of text."
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    logger.info(f"Resume updated: {RESUME_PATH} ({size_kb:.1f} KB)")
    return f"Resume updated successfully ({size_kb:.1f} KB).{page_info} It will be used for future job applications."
