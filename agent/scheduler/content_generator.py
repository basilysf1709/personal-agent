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
        "Choose from: calculus, linear algebra, number theory, topology, probability, combinatorics. "
        "The LaTeX field is REQUIRED — provide a beautiful, non-trivial equation."
    ),
    "coding_tips": (
        "Generate a famous or beautiful equation from computer science or information theory. "
        "Examples: Shannon entropy, Big-O recurrences, Bellman equation, RSA, Bayes' theorem. "
        "The LaTeX field is REQUIRED."
    ),
    "science_facts": (
        "Generate a famous scientific equation or formula. "
        "Cover: thermodynamics, chemistry, biology, astronomy, neuroscience. "
        "Examples: Drake equation, Nernst equation, Boltzmann distribution. "
        "The LaTeX field is REQUIRED."
    ),
    "motivational_quotes": (
        "Generate a beautiful mathematical identity or theorem. "
        "Examples: Ramanujan's infinite series, continued fractions, golden ratio identities. "
        "The LaTeX field is REQUIRED."
    ),
    "tech_insights": (
        "Generate an equation from systems/engineering. "
        "Examples: Amdahl's law, Little's law, queuing theory, CAP theorem formalization. "
        "The LaTeX field is REQUIRED."
    ),
    "algorithm_visualizations": (
        "Generate a key algorithm recurrence or complexity equation. "
        "Examples: Master theorem, DP recurrences, graph algorithm bounds. "
        "The LaTeX field is REQUIRED."
    ),
    "physics_concepts": (
        "Generate a beautiful physics equation. "
        "Cover: mechanics, electromagnetism, thermodynamics, quantum mechanics, relativity, optics. "
        "Examples: Maxwell's equations, Schrodinger equation, Einstein field equations. "
        "The LaTeX field is REQUIRED."
    ),
    "historical_tech_moments": (
        "Generate a historically significant mathematical equation or formula. "
        "Examples: Euler's formula, Fourier transform, Laplace transform, Gauss's law. "
        "The LaTeX field is REQUIRED."
    ),
}

SYSTEM_PROMPT = """\
You are a content creator for educational social media posts showcasing beautiful LaTeX equations.
Every post MUST feature a LaTeX equation as the centerpiece.

Respond ONLY with valid JSON in this exact format:
{
  "title": "Name of the equation/formula (max 50 chars)",
  "body": "One sentence explaining what this equation means or why it matters",
  "latex": "The LaTeX equation (just the math, no document wrapper) — THIS IS REQUIRED",
  "hashtags": ["latex", "math", "equations"],
  "caption": "Try useoctree.com to compile LaTeX instantly! #latex"
}

Rules:
- The LaTeX field is REQUIRED — never return null
- Title: name of the equation (e.g. "Euler's Identity", "Fourier Transform")
- Body: one short sentence about the equation
- LaTeX: the equation itself, raw LaTeX math (no \\begin{document}, no $$ wrappers)
- Hashtags: always include "latex" as the first tag, then 2-4 relevant math/science tags
- Caption: always start with "Try useoctree.com" and include #latex"""


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
