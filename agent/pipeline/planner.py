"""
IncrementalPlanner — Phase 4, Step 1 of the MODIFY pipeline.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..intelligence.context import RepositoryContext
from ..llm.router import ModelRouter
from .models import IncrementalPlan, PlanStep

PLANNER_SYSTEM_PROMPT = """You are NERO's Planning Engine.

Your ONLY job is to produce a structured modification plan in JSON.

You will receive:
  1. A Repository Intelligence context block (language, framework, routes, files)
  2. The user's modification request

You must output a single JSON object with EXACTLY this schema:
{
  "goal": "one-sentence restatement of the user's goal",
  "understanding": "your analysis of what needs to change and why",
  "approach": "high-level strategy in one paragraph",
  "affected_files": ["relative/path/to/file1", "relative/path/to/file2"],
  "steps": [
    {
      "id": 1,
      "description": "What this step does (imperative, specific, actionable)",
      "target_files": ["relative/path/to/file"]
    }
  ],
  "validation_commands": ["npm test", "pytest"],
  "risks": ["Risk 1", "Risk 2"]
}

RULES:
- Output ONLY the JSON. No prose before or after.
- Steps must be in dependency order (each step can depend on the previous).
- Each step must be a single, atomic, verifiable action.
- target_files must use forward slashes and be relative to the repo root.
- validation_commands must come from: npm test, npm run test, pytest, python -m pytest,
  go test, cargo test, mvn test, gradle test, ruff check, flake8.
- If you don't know the correct validation command, use an empty list.
- If a file's exact path is unknown, use the most likely path from the context.
- Be conservative: fewer, clearer steps are better than many vague ones.
- Maximum 12 steps. If the task needs more, break it into the 12 most important.
"""


class PlannerError(Exception):
    """Raised when the planner cannot produce a valid plan."""
    pass


class IncrementalPlanner:
    """Calls the LLM planner role to produce a typed IncrementalPlan."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    def plan(
        self,
        user_request: str,
        repo_context: RepositoryContext,
    ) -> IncrementalPlan:
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "system", "content": repo_context.format_context_summary()},
            {"role": "user", "content": user_request},
        ]

        last_error: Optional[Exception] = None
        raw = ""

        for attempt in range(1, 3):
            try:
                response = self._router.chat("planner", messages, stream=True)
                raw = response.content or ""
                plan = self._parse_plan(raw, model_used=response.model_used)
                return plan
            except Exception as exc:
                last_error = exc
                if attempt == 1:
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": f"Your response was not a valid JSON plan. Error: {exc}. Please output ONLY the valid JSON plan matching the requested schema.",
                    })
                continue

        raise PlannerError(
            f"Planner failed after retries. Last error: {last_error}"
        )

    def _parse_plan(self, raw: str, model_used: str = "") -> IncrementalPlan:
        cleaned = raw.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", cleaned, re.I)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        obj_match = re.search(r"\{[\s\S]+\}", cleaned)
        if not obj_match:
            raise PlannerError(
                f"LLM response contains no JSON object.\nResponse: {raw[:500]}"
            )

        try:
            data: Dict[str, Any] = json.loads(obj_match.group())
        except json.JSONDecodeError as exc:
            raise PlannerError(
                f"Failed to parse plan JSON: {exc}\nRaw: {raw[:500]}"
            ) from exc

        for required in ("goal", "steps"):
            if required not in data:
                raise PlannerError(
                    f"Plan JSON missing required field '{required}'.\nData: {data}"
                )

        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("Plan must have at least one step.")

        steps: List[PlanStep] = []
        for i, s in enumerate(raw_steps[:12]):
            if not isinstance(s, dict):
                continue
            steps.append(PlanStep(
                id=int(s.get("id", i + 1)),
                description=str(s.get("description", f"Step {i + 1}")),
                target_files=[
                    str(f) for f in s.get("target_files", [])
                    if isinstance(f, str)
                ],
            ))

        if not steps:
            raise PlannerError("No valid steps could be parsed from the plan.")

        return IncrementalPlan(
            goal=str(data.get("goal", "Unknown goal")),
            understanding=str(data.get("understanding", "")),
            approach=str(data.get("approach", "")),
            affected_files=[
                str(f) for f in data.get("affected_files", [])
                if isinstance(f, str)
            ],
            steps=steps,
            validation_commands=[
                str(c) for c in data.get("validation_commands", [])
                if isinstance(c, str)
            ],
            risks=[
                str(r) for r in data.get("risks", [])
                if isinstance(r, str)
            ],
            created_at=datetime.now().isoformat(),
            model_used=model_used,
        )
