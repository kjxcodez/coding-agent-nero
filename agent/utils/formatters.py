"""
Formatters and string sanitizers for LLM outputs and JSON payloads.
"""

import json
import re
from typing import Any, Dict


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_json_safely(text: str) -> Dict[str, Any]:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Failed to parse valid JSON from text: {text[:200]}...")


def truncate_text(text: str, max_chars: int = 300) -> str:
    flat = text.replace("\n", " ")
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars] + f"... ({len(text)} chars total)"
