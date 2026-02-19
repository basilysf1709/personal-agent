import asyncio
import base64
import logging
import os
import subprocess
import time
import anthropic
from kernel import AsyncKernel

logger = logging.getLogger(__name__)

APPLY_TO_JOB_SCHEMA = {
    "name": "apply_to_job",
    "description": (
        "Apply to a job listing by navigating to the URL and filling out the application form using browser automation. "
        "Provide the job listing URL. A resume PDF should be stored at /app/data/resume.pdf."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "job_url": {
                "type": "string",
                "description": "The URL of the job listing to apply to",
            },
            "resume_path": {
                "type": "string",
                "description": "Path to the resume PDF file (default: /app/data/resume.pdf)",
                "default": "/app/data/resume.pdf",
            },
        },
        "required": ["job_url"],
    },
}

MODEL = "claude-sonnet-4-5-20250929"
MAX_ITERATIONS = 75
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 800

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "profile.md")

# Resume path inside the Kernel VM
KERNEL_RESUME_PATH = "/tmp/resume.pdf"

INNER_SYSTEM_PROMPT = """\
You are a job application assistant controlling a web browser. Your goal is to navigate a job listing page and complete the application.

Instructions:
- You can see screenshots of the browser and control it with mouse/keyboard actions.
- Find the "Apply" button or scroll down to the application form and fill it out.
- Fill in all required fields using the applicant profile and resume information provided below.
- For file upload fields (resume/CV): simply click on the upload button/area. The system will automatically attach the resume PDF — you do NOT need to interact with any file dialog.
- Submit the application when all fields are filled.
- If the site requires login/account creation, STOP and report that to the user — do not try to create accounts.
- If you see a CAPTCHA or similar test (reCAPTCHA, hCaptcha, etc.), just wait for it to get solved automatically by the browser. Take a screenshot after a few seconds to check if it was solved. Do NOT try to solve CAPTCHAs yourself.
- If you encounter a Cloudflare challenge, wait for the "Ready" message to appear. Once it does, continue with your intended actions — do NOT click the Cloudflare checkbox, as this can interfere with the auto-solver.
- When you are done (application submitted, or blocked), respond with a text message summarizing what happened. Do NOT use the computer tool when you are done.

Applicant profile:
{profile_text}

Resume content:
{resume_text}
"""


def _load_profile() -> str:
    """Load the applicant profile from assets/profile.md."""
    try:
        with open(PROFILE_PATH, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "[No profile.md found. Use resume content only.]"


def _extract_resume_text(resume_path: str) -> str:
    """Extract text content from a PDF resume."""
    try:
        result = subprocess.run(
            ["pdftotext", resume_path, "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open(resume_path, "rb") as f:
            # Return a note that the PDF exists but couldn't be parsed
            f.read(10)  # just check it's readable
            return f"[Resume PDF exists at {resume_path} but text extraction is unavailable. Use the file for uploads.]"
    except FileNotFoundError:
        return "[No resume file found. Ask the user to provide their details or upload a resume.]"


async def _take_screenshot(kernel_client: AsyncKernel, session_id: str) -> str:
    """Take a screenshot via Kernel Computer Controls and return base64."""
    response = await kernel_client.browsers.computer.capture_screenshot(session_id)
    screenshot_bytes = response.read()
    return base64.b64encode(screenshot_bytes).decode()


def _screenshot_content(screenshot_b64: str) -> list:
    """Build image content block for Claude from base64 screenshot."""
    return [{
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": screenshot_b64,
        },
    }]


async def _run_computer_use_loop(job_url: str, resume_path: str) -> str:
    """Run the Computer Use agent loop with Kernel cloud browser."""
    profile_text = _load_profile()
    resume_text = _extract_resume_text(resume_path)
    system_prompt = INNER_SYSTEM_PROMPT.format(
        resume_path=resume_path,
        profile_text=profile_text,
        resume_text=resume_text,
    )

    kernel_client = AsyncKernel(api_key=os.environ.get("KERNEL_API_KEY"))

    # Create a stealth cloud browser via Kernel
    logger.info("Creating Kernel browser session (stealth mode)...")
    kernel_browser = await kernel_client.browsers.create(
        stealth=True,
        viewport={
            "width": DISPLAY_WIDTH,
            "height": DISPLAY_HEIGHT,
        },
        timeout_seconds=600,  # 10 min inactivity timeout
    )
    session_id = kernel_browser.session_id
    live_view_url = kernel_browser.browser_live_view_url
    logger.info(f"Kernel session: {session_id}")
    if live_view_url:
        logger.info(f"Live view: {live_view_url}")

    try:
        # Upload resume to the Kernel VM via Playwright execute
        if os.path.exists(resume_path):
            logger.info(f"Uploading resume to Kernel VM: {KERNEL_RESUME_PATH}")
            with open(resume_path, "rb") as f:
                resume_b64 = base64.b64encode(f.read()).decode()
            upload_code = f"""
                const fs = require('fs');
                const data = Buffer.from(`{resume_b64}`, 'base64');
                fs.writeFileSync('{KERNEL_RESUME_PATH}', data);
                return 'wrote ' + data.length + ' bytes';
            """
            upload_result = await kernel_client.browsers.playwright.execute(
                session_id, code=upload_code, timeout_sec=15,
            )
            logger.info(f"Resume upload: {upload_result.result}")

        # Navigate to the job URL and set up file chooser handling via Playwright
        logger.info(f"Navigating to {job_url}")
        nav_code = f"""
            // Auto-handle file upload dialogs by attaching the resume
            page.on('filechooser', async (fc) => {{
                await fc.setFiles('{KERNEL_RESUME_PATH}');
            }});
            await page.goto('{job_url}', {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
            await page.waitForTimeout(2000);
            return 'ok';
        """
        try:
            await kernel_client.browsers.playwright.execute(
                session_id,
                code=nav_code,
                timeout_sec=40,
            )
        except Exception as e:
            return f"Failed to load job URL: {e}"

        # Take initial screenshot
        screenshot_b64 = await _take_screenshot(kernel_client, session_id)

        client = anthropic.Anthropic()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Apply to this job: {job_url}",
                    },
                ],
            }
        ]

        computer_tool = {
            "type": "computer_20250124",
            "name": "computer",
            "display_width_px": DISPLAY_WIDTH,
            "display_height_px": DISPLAY_HEIGHT,
            "display_number": 0,
        }

        summary = "Job application process did not complete."

        for iteration in range(MAX_ITERATIONS):
            logger.info(f"Computer Use iteration {iteration + 1}/{MAX_ITERATIONS}")
            try:
                response = client.beta.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=[computer_tool],
                    messages=messages,
                    betas=["computer-use-2025-01-24"],
                )
            except Exception as e:
                logger.error(f"Claude API error on iteration {iteration + 1}: {e}")
                summary = f"Claude API error: {e}"
                break

            # Check if Claude is done (text response, no tool use)
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_parts = [b.text for b in response.content if b.type == "text"]
            logger.info(f"  Response: stop_reason={response.stop_reason} tool_uses={len(tool_uses)} text_parts={len(text_parts)}")
            if text_parts:
                logger.info(f"  Text: {text_parts[0][:300]}")

            if not tool_uses:
                summary = "\n".join(text_parts) if text_parts else summary
                logger.info(f"Computer Use agent finished: {summary[:200]}")
                break

            # Append assistant message
            messages.append({"role": "assistant", "content": response.content})

            # Process each tool use
            tool_results = []
            for tool_use in tool_uses:
                action = tool_use.input.get("action")
                coordinate = tool_use.input.get("coordinate", [])
                text_input = tool_use.input.get("text", "")
                logger.info(f"  Action: {action} coordinate={coordinate} text={text_input[:50] if text_input else ''}")
                result_content = []

                try:
                    if action == "screenshot":
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action in ("click", "left_click", "right_click", "middle_click"):
                        x, y = tool_use.input.get("coordinate", [0, 0])
                        button_map = {"right_click": "right", "middle_click": "middle"}
                        button = button_map.get(action, "left")
                        await kernel_client.browsers.computer.click_mouse(
                            session_id, x=x, y=y, button=button,
                        )
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "double_click":
                        x, y = tool_use.input.get("coordinate", [0, 0])
                        await kernel_client.browsers.computer.click_mouse(
                            session_id, x=x, y=y, num_clicks=2,
                        )
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "triple_click":
                        x, y = tool_use.input.get("coordinate", [0, 0])
                        await kernel_client.browsers.computer.click_mouse(
                            session_id, x=x, y=y, num_clicks=3,
                        )
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "left_click_drag":
                        start = tool_use.input.get("start_coordinate", [0, 0])
                        end = tool_use.input.get("coordinate", [0, 0])
                        await kernel_client.browsers.computer.drag_mouse(
                            session_id,
                            path=[start, end],
                            button="left",
                        )
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "drag":
                        start = tool_use.input.get("start_coordinate", [0, 0])
                        end = tool_use.input.get("end_coordinate", [0, 0])
                        await kernel_client.browsers.computer.drag_mouse(
                            session_id,
                            path=[start, end],
                        )
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "type":
                        text = tool_use.input.get("text", "")
                        await kernel_client.browsers.computer.type_text(
                            session_id, text=text, delay=50,
                        )
                        await asyncio.sleep(0.3)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "key":
                        key = tool_use.input.get("key", "")
                        # Kernel uses X11 keysym names
                        key_map = {
                            "Enter": "Return",
                            "Backspace": "BackSpace",
                            " ": "space",
                        }
                        kernel_key = key_map.get(key, key)
                        await kernel_client.browsers.computer.press_key(
                            session_id, keys=[kernel_key],
                        )
                        await asyncio.sleep(0.3)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "scroll":
                        cx = tool_use.input.get("coordinate", [DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2])[0]
                        cy = tool_use.input.get("coordinate", [DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2])[1]
                        direction = tool_use.input.get("direction", "down")
                        amount = tool_use.input.get("amount", 3)
                        delta = amount * 100
                        delta_x, delta_y = 0, 0
                        if direction == "down":
                            delta_y = delta
                        elif direction == "up":
                            delta_y = -delta
                        elif direction == "right":
                            delta_x = delta
                        elif direction == "left":
                            delta_x = -delta
                        await kernel_client.browsers.computer.scroll(
                            session_id, x=cx, y=cy, delta_x=delta_x, delta_y=delta_y,
                        )
                        await asyncio.sleep(0.3)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    elif action == "cursor_position":
                        pos = await kernel_client.browsers.computer.get_mouse_position(session_id)
                        result_content = [{
                            "type": "text",
                            "text": f"Cursor position: ({pos.x}, {pos.y})",
                        }]

                    elif action == "wait":
                        duration = tool_use.input.get("duration", 2)
                        await asyncio.sleep(duration)
                        screenshot_b64 = await _take_screenshot(kernel_client, session_id)
                        result_content = _screenshot_content(screenshot_b64)

                    else:
                        result_content = [{
                            "type": "text",
                            "text": f"Unknown action: {action}",
                        }]

                except Exception as e:
                    result_content = [{
                        "type": "text",
                        "text": f"Error executing {action}: {e}",
                    }]

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_content,
                })

            messages.append({"role": "user", "content": tool_results})

    finally:
        # Clean up the Kernel browser session
        try:
            await kernel_client.browsers.delete_by_id(session_id)
            logger.info(f"Kernel session {session_id} deleted")
        except Exception as e:
            logger.warning(f"Failed to delete Kernel session: {e}")

    return summary


def apply_to_job(job_url: str, resume_path: str = "/app/data/resume.pdf") -> str:
    """Apply to a job listing using browser automation with Claude Computer Use."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, _run_computer_use_loop(job_url, resume_path)
                ).result(timeout=600)
            return result
        else:
            return loop.run_until_complete(
                _run_computer_use_loop(job_url, resume_path)
            )
    except RuntimeError:
        return asyncio.run(_run_computer_use_loop(job_url, resume_path))
    except Exception as e:
        return f"Error during job application: {e}"
