"""Claude-based content generation with variety enforcement."""

import json
import logging

import anthropic

from agent.scheduler.state import CATEGORIES

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5-20250929"

CATEGORY_PROMPTS: dict[str, str] = {
    "math_equations": (
        "Generate a visually striking mathematical equation, identity, or formula. "
        "Include the LaTeX representation and a brief explanation of why it's beautiful or useful. "
        "Choose from: calculus, linear algebra, number theory, topology, probability, combinatorics."
    ),
    "coding_tips": (
        "Generate a practical coding tip with a short code snippet. "
        "Pick a language from Python, Go, Rust, or TypeScript. "
        "Topics: clever stdlib usage, performance tricks, common pitfalls, elegant patterns."
    ),
    "science_facts": (
        "Generate a mind-blowing science fact that most people don't know. "
        "Cover biology, chemistry, astronomy, geology, or neuroscience. "
        "Include one key number or measurement that makes it tangible."
    ),
    "motivational_quotes": (
        "Generate an original motivational quote for builders, engineers, and creators. "
        "NOT a famous quote — create something new and sharp. "
        "Add a one-line reflection on why it matters."
    ),
    "tech_insights": (
        "Generate an insight about software architecture, engineering principles, or system design. "
        "Topics: distributed systems, API design, scaling patterns, reliability, developer experience."
    ),
    "algorithm_visualizations": (
        "Generate a step-by-step breakdown of an algorithm. "
        "Show the key steps with small examples. "
        "Choose from: sorting, graph, dynamic programming, tree, string, or greedy algorithms."
    ),
    "physics_concepts": (
        "Generate an explanation of a physics concept with its key equation. "
        "Include the LaTeX for the equation. "
        "Cover: mechanics, electromagnetism, thermodynamics, quantum mechanics, relativity, optics."
    ),
    "historical_tech_moments": (
        "Generate a post about a pivotal moment in computing history. "
        "Include the year, the person/team, and why it changed everything. "
        "Cover: hardware breakthroughs, language creation, internet milestones, AI landmarks."
    ),
}

SYSTEM_PROMPT = """\
You are a content creator for educational social media posts (Instagram & TikTok).
Generate content that is informative, visually appealing, and engaging.

Respond ONLY with valid JSON in this exact format:
{
  "title": "Short catchy title (max 60 chars)",
  "body": "Main content text (2-4 paragraphs, each 1-2 sentences)",
  "latex": "LaTeX equation if applicable (just the math, no document wrapper), or null",
  "code": "Code snippet if applicable, or null",
  "code_language": "Language name if code is provided, or null",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "caption": "Instagram/TikTok caption (engaging, with emoji, 1-2 sentences + hashtags)"
}

Rules:
- Title must be attention-grabbing and concise
- Body should educate and inspire — write for curious minds
- If the category involves math or physics, include LaTeX for the key equation
- If the category is coding_tips, include a code snippet
- Hashtags: 5 relevant ones, no # prefix
- Caption: write as if posting to Instagram — conversational, with emoji"""


def generate_content(category: str, recent_titles: list[str]) -> dict:
    """Generate content for a given category using Claude.

    Returns dict with keys: title, body, latex, code, code_language, hashtags, caption
    """
    if category not in CATEGORY_PROMPTS:
        raise ValueError(f"Unknown category: {category}. Valid: {CATEGORIES}")

    avoid_block = ""
    if recent_titles:
        titles_str = "\n".join(f"- {t}" for t in recent_titles)
        avoid_block = (
            f"\n\nDo NOT repeat or closely resemble any of these recent titles:\n{titles_str}\n"
            "Be creative and pick a DIFFERENT topic within this category."
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Category: {category}\n\n{CATEGORY_PROMPTS[category]}{avoid_block}",
            }
        ],
    )

    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("Claude returned invalid JSON: %s", text[:500])
        raise RuntimeError("Content generation failed: invalid JSON from Claude")

    required = {"title", "body", "hashtags", "caption"}
    missing = required - set(data.keys())
    if missing:
        raise RuntimeError(f"Content generation missing fields: {missing}")

    return data
