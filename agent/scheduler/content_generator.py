"""Claude-based content generation with variety across content types."""

import json
import logging

import anthropic

from agent.scheduler.state import CONTENT_TYPES

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5-20250929"

# Each content type has its own prompt and expected fields
TYPE_PROMPTS: dict[str, str] = {
    "equation": (
        "Generate a visually striking mathematical or scientific equation. "
        "Pick from: calculus, linear algebra, number theory, physics, information theory, "
        "thermodynamics, quantum mechanics, relativity, signal processing, probability. "
        "Examples: Euler's identity, Fourier transform, Schrodinger equation, Bayes' theorem, "
        "Maxwell's equations, Navier-Stokes, Boltzmann distribution, Master theorem."
    ),
    "code_snippet": (
        "Generate a practical, elegant coding tip with a short code snippet (5-15 lines). "
        "Pick a language from: Python, Go, Rust, TypeScript, C, Java, Haskell. "
        "Topics: clever stdlib usage, performance tricks, elegant patterns, one-liners, "
        "concurrency patterns, functional tricks, data structure hacks, API design."
    ),
    "definition": (
        "Explain a computer science, math, or engineering concept clearly and concisely. "
        "Topics: data structures, algorithms, design patterns, networking protocols, "
        "cryptography primitives, type systems, complexity classes, database internals, "
        "compiler concepts, OS concepts, distributed systems, category theory."
    ),
    "fact": (
        "Generate a mind-blowing science, math, or tech fact with a key number or measurement. "
        "Topics: biology, astronomy, neuroscience, computing history, physics, chemistry, "
        "internet scale, hardware limits, mathematical curiosities, nature's patterns."
    ),
    "quote": (
        "Generate a sharp, memorable quote for engineers, builders, and creators. "
        "It can be a famous quote from a real person (scientist, engineer, mathematician, "
        "programmer) OR an original insightful quote. Must feel authentic and punchy."
    ),
    "resume": (
        "Generate a polished resume/CV snippet showcasing LaTeX's typesetting power. "
        "Create a fictional but realistic professional profile with: name, title, "
        "2-3 bullet point achievements, and a skills section. "
        "Pick from: software engineer, data scientist, ML researcher, quant trader, "
        "robotics engineer, security researcher, systems architect, PhD candidate. "
        "Make it look like a real high-quality LaTeX resume section."
    ),
    "presentation": (
        "Generate a single presentation slide showcasing LaTeX Beamer's power. "
        "Pick a topic from: tech talks, conference keynotes, lecture slides, startup pitches, "
        "research presentations, workshop tutorials. "
        "Include a slide title, 3-4 bullet points, and optionally a key equation or diagram description. "
        "Make it look like a real Beamer slide."
    ),
    "research": (
        "Generate a short research paper snippet (abstract or key result) showcasing LaTeX's "
        "academic typesetting. Pick a field: machine learning, cryptography, quantum computing, "
        "distributed systems, computational biology, theoretical CS, robotics, NLP. "
        "Include a paper title, authors (fictional), and a 2-3 sentence abstract with "
        "one key equation or result."
    ),
}

SYSTEM_PROMPT = """\
You are a content creator for educational social media posts. Each post promotes useoctree.com (a LaTeX compiler).
You will be given a content_type — generate content matching that type exactly.

Respond ONLY with valid JSON matching the content_type:

For content_type "equation":
{
  "content_type": "equation",
  "title": "Name of equation (max 50 chars)",
  "body": "One sentence about what it means",
  "latex": "Raw LaTeX math — REQUIRED, no wrappers",
  "hashtags": ["latex", "math", "equations", "stem", "science"],
  "caption": "Creative engaging caption here. Link in bio! #latex #math #stem"
}

For content_type "code_snippet":
{
  "content_type": "code_snippet",
  "title": "Short title (max 50 chars)",
  "body": "One sentence explaining the tip",
  "code": "The code snippet (5-15 lines)",
  "code_language": "Python",
  "hashtags": ["coding", "programming", "developer", "tech", "latex"],
  "caption": "Creative engaging caption here. Link in bio! #coding #programming #developer"
}

For content_type "definition":
{
  "content_type": "definition",
  "title": "The Concept Name",
  "body": "Clear 2-3 sentence explanation of the concept",
  "key_term": "The one key term being defined",
  "hashtags": ["computerscience", "learning", "tech", "coding", "latex"],
  "caption": "Creative engaging caption here. Link in bio! #computerscience #learning #tech"
}

For content_type "fact":
{
  "content_type": "fact",
  "title": "Short catchy title (max 50 chars)",
  "body": "The full fact in 1-2 sentences",
  "big_number": "The key number/stat (e.g. '86 billion', '299,792,458 m/s')",
  "hashtags": ["science", "didyouknow", "facts", "stem", "latex"],
  "caption": "Creative engaging caption here. Link in bio! #science #didyouknow #facts"
}

For content_type "quote":
{
  "content_type": "quote",
  "title": "Topic of the quote (max 30 chars)",
  "body": "The quote text itself — punchy and memorable",
  "attribution": "Person's name and role, or 'Unknown' if original",
  "hashtags": ["motivation", "engineering", "quotes", "inspiration", "latex"],
  "caption": "Creative engaging caption here. Link in bio! #motivation #engineering #quotes"
}

For content_type "resume":
{
  "content_type": "resume",
  "title": "LaTeX Resume Showcase (max 50 chars)",
  "body": "One sentence about why LaTeX resumes stand out",
  "name": "Full Name",
  "job_title": "Senior Software Engineer",
  "achievements": ["Led migration of...", "Reduced latency by...", "Published 3 papers on..."],
  "skills": ["Python", "Rust", "Kubernetes", "ML"],
  "hashtags": ["resume", "latex", "career", "jobs", "tech"],
  "caption": "Creative engaging caption here. Link in bio! #resume #latex #career"
}

For content_type "presentation":
{
  "content_type": "presentation",
  "title": "Slide title (max 50 chars)",
  "body": "One sentence describing the presentation topic",
  "slide_title": "The title shown on the slide",
  "bullets": ["First key point", "Second key point", "Third key point"],
  "slide_equation": "Optional LaTeX equation for the slide (or empty string)",
  "hashtags": ["presentation", "latex", "beamer", "tech", "slides"],
  "caption": "Creative engaging caption here. Link in bio! #presentation #latex #beamer"
}

For content_type "research":
{
  "content_type": "research",
  "title": "Paper title (max 60 chars)",
  "body": "2-3 sentence abstract of the paper",
  "authors": ["Alice Chen", "Bob Smith", "Carol Zhang"],
  "institution": "MIT CSAIL",
  "key_equation": "Optional key LaTeX equation from the paper (or empty string)",
  "hashtags": ["research", "latex", "academia", "science", "paper"],
  "caption": "Creative engaging caption here. Link in bio! #research #latex #academia"
}

CAPTION RULES (CRITICAL):
- Every caption MUST include the phrase "Link in bio" somewhere
- Be creative and engaging — write like a real social media creator
- Use relevant emojis naturally
- Include 3-5 hashtags at the end
- Don't be generic — make people want to engage
- Vary your caption style: ask questions, share insights, use hooks

GENERAL RULES:
- Keep content concise and visually appealing
- Be creative — avoid generic or overused content
- Hashtags: 4-6 relevant ones, no # prefix in the array"""


def generate_content(content_type: str, recent_titles: list[str]) -> dict:
    """Generate content for a given content type using Claude.

    Returns a dict with type-specific fields.
    """
    if content_type not in TYPE_PROMPTS:
        raise ValueError(f"Unknown content type: {content_type}. Valid: {CONTENT_TYPES}")

    avoid_block = ""
    if recent_titles:
        titles_str = "\n".join(f"- {t}" for t in recent_titles)
        avoid_block = (
            f"\n\nDo NOT repeat or closely resemble any of these recent titles:\n{titles_str}\n"
            "Be creative and pick a DIFFERENT topic."
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"content_type: {content_type}\n\n"
                    f"{TYPE_PROMPTS[content_type]}{avoid_block}"
                ),
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

    # Ensure content_type is set
    data["content_type"] = content_type
    return data
