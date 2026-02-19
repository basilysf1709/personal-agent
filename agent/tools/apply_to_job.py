import asyncio
import base64
import logging
import os
import subprocess
import anthropic
from playwright.async_api import async_playwright

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
MAX_ITERATIONS = 30
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 800

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "profile.md")

INNER_SYSTEM_PROMPT = """\
You are a job application assistant controlling a web browser. Your goal is to navigate a job listing page and complete the application.

Instructions:
- You can see screenshots of the browser and control it with mouse/keyboard actions.
- Find the "Apply" button or scroll down to the application form and fill it out.
- Fill in all required fields using the applicant profile and resume information provided below.
- For file upload fields (resume/CV): simply click on the upload button/area. The system will automatically attach the resume PDF — you do NOT need to interact with any file dialog.
- Submit the application when all fields are filled.
- If the site requires login/account creation, STOP and report that to the user — do not try to create accounts.
- If you encounter a CAPTCHA you cannot solve, STOP and report it.
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


async def _run_computer_use_loop(job_url: str, resume_path: str) -> str:
    """Run the Computer Use agent loop with Playwright."""
    profile_text = _load_profile()
    resume_text = _extract_resume_text(resume_path)
    system_prompt = INNER_SYSTEM_PROMPT.format(
        resume_path=resume_path,
        profile_text=profile_text,
        resume_text=resume_text,
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": DISPLAY_WIDTH, "height": DISPLAY_HEIGHT},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Auto-handle file upload dialogs by attaching the resume
        async def _handle_filechooser(fc):
            logger.info(f"File chooser triggered, uploading: {resume_path}")
            await fc.set_files(resume_path)
        page.on("filechooser", lambda fc: asyncio.ensure_future(_handle_filechooser(fc)))

        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)  # let JS render
        except Exception as e:
            await browser.close()
            return f"Failed to load job URL: {e}"

        # Take initial screenshot
        screenshot_bytes = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

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

        mouse_x, mouse_y = 0, 0
        summary = "Job application process did not complete."

        for iteration in range(MAX_ITERATIONS):
            logger.info(f"Computer Use iteration {iteration + 1}/{MAX_ITERATIONS}")
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_prompt,
                tools=[computer_tool],
                messages=messages,
                betas=["computer-use-2025-01-24"],
            )

            # Check if Claude is done (text response, no tool use)
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_parts = [b.text for b in response.content if b.type == "text"]

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
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action in ("click", "left_click", "right_click", "middle_click"):
                        x = tool_use.input.get("coordinate", [0, 0])[0]
                        y = tool_use.input.get("coordinate", [0, 0])[1]
                        button_map = {"right_click": "right", "middle_click": "middle"}
                        pw_button = button_map.get(action, "left")
                        await page.mouse.click(x, y, button=pw_button)
                        mouse_x, mouse_y = x, y
                        await page.wait_for_timeout(500)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action in ("double_click", "left_click_drag"):
                        if action == "left_click_drag":
                            start = tool_use.input.get("start_coordinate", [0, 0])
                            end = tool_use.input.get("coordinate", [0, 0])
                            await page.mouse.move(start[0], start[1])
                            await page.mouse.down()
                            await page.mouse.move(end[0], end[1])
                            await page.mouse.up()
                            x, y = end[0], end[1]
                        else:
                            x = tool_use.input.get("coordinate", [0, 0])[0]
                            y = tool_use.input.get("coordinate", [0, 0])[1]
                            await page.mouse.dblclick(x, y)
                        mouse_x, mouse_y = x, y
                        await page.wait_for_timeout(500)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "type":
                        text = tool_use.input.get("text", "")
                        await page.keyboard.type(text, delay=50)
                        await page.wait_for_timeout(300)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "key":
                        key = tool_use.input.get("key", "")
                        # Map Computer Use key names to Playwright key names
                        key_map = {
                            "Return": "Enter",
                            "BackSpace": "Backspace",
                            "space": " ",
                            "Tab": "Tab",
                            "Escape": "Escape",
                        }
                        pw_key = key_map.get(key, key)
                        await page.keyboard.press(pw_key)
                        await page.wait_for_timeout(300)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "scroll":
                        x = tool_use.input.get("coordinate", [DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2])[0]
                        y = tool_use.input.get("coordinate", [DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2])[1]
                        direction = tool_use.input.get("direction", "down")
                        amount = tool_use.input.get("amount", 3)
                        delta = amount * 100
                        if direction == "up":
                            delta = -delta
                        elif direction == "left":
                            await page.mouse.move(x, y)
                            await page.evaluate(f"window.scrollBy(-{delta}, 0)")
                            await page.wait_for_timeout(300)
                            screenshot_bytes = await page.screenshot()
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                            result_content = [{
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            }]
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": result_content,
                            })
                            continue
                        elif direction == "right":
                            await page.mouse.move(x, y)
                            await page.evaluate(f"window.scrollBy({delta}, 0)")
                            await page.wait_for_timeout(300)
                            screenshot_bytes = await page.screenshot()
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                            result_content = [{
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            }]
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": result_content,
                            })
                            continue

                        await page.mouse.move(x, y)
                        await page.mouse.wheel(0, delta)
                        await page.wait_for_timeout(300)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "cursor_position":
                        result_content = [{
                            "type": "text",
                            "text": f"Cursor position: ({mouse_x}, {mouse_y})",
                        }]

                    elif action == "drag":
                        start = tool_use.input.get("start_coordinate", [0, 0])
                        end = tool_use.input.get("end_coordinate", [0, 0])
                        await page.mouse.move(start[0], start[1])
                        await page.mouse.down()
                        await page.mouse.move(end[0], end[1])
                        await page.mouse.up()
                        mouse_x, mouse_y = end[0], end[1]
                        await page.wait_for_timeout(500)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "triple_click":
                        x = tool_use.input.get("coordinate", [0, 0])[0]
                        y = tool_use.input.get("coordinate", [0, 0])[1]
                        await page.mouse.click(x, y, click_count=3)
                        mouse_x, mouse_y = x, y
                        await page.wait_for_timeout(500)
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

                    elif action == "wait":
                        duration = tool_use.input.get("duration", 2)
                        await page.wait_for_timeout(int(duration * 1000))
                        screenshot_bytes = await page.screenshot()
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                        result_content = [{
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        }]

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

        await browser.close()

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
                ).result(timeout=300)
            return result
        else:
            return loop.run_until_complete(
                _run_computer_use_loop(job_url, resume_path)
            )
    except RuntimeError:
        return asyncio.run(_run_computer_use_loop(job_url, resume_path))
    except Exception as e:
        return f"Error during job application: {e}"
