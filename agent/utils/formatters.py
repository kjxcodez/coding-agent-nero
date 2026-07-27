"""
Formatters and string sanitizers for LLM outputs and JSON payloads.
"""

import re, json

from typing import Any, Dict



def strip_code_fences(text: str) -> str:
    """Removes markdown code fences (```json ... ```) from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening line if it starts with ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing line if it starts with ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_json_safely(text: str) -> Dict[str, Any]:
    """Attempts to parse JSON from raw text, stripping code fences if needed."""
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Match JSON block using regex if wrapped in extra prose
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Failed to parse valid JSON from text: {text[:200]}...")


def truncate_text(text: str, max_chars: int = 300) -> str:
    """Truncates text for log display."""
    flat = text.replace("\n", " ")
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars] + f"... ({len(text)} chars total)"
