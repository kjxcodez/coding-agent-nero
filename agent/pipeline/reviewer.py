"""
ReviewerAgent — Phase 4, Step 5 of the MODIFY pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..llm.router import ModelRouter
from ..utils.logger import AgentLogger
from .models import ReviewResult, IncrementalPlan

REVIEWER_SYSTEM_PROMPT = """You are NERO's Code Reviewer.

You will receive:
  1. The original user intent (what they asked for)
  2. The active git diff (what was actually changed)
  3. The verification result (did tests pass?)
  4. The current plan execution status (completed vs pending steps)
  5. The history of repair attempts (if any failed tests had to be repaired)

Your job is to compare intent vs. implementation and produce a JSON review:
{
  "approved": true or false,
  "summary": "one-paragraph assessment of the changes",
  "concerns": ["concern 1", "concern 2"],
  "suggestions": ["suggestion 1", "suggestion 2"]
}

RULES:
- Output ONLY the JSON. No prose before or after.
- "approved" is true if the changes correctly and safely implement the user's intent.
- "approved" is false if: changes are incomplete, incorrect, introduce bugs,
  have security issues, or significantly deviate from intent.
- You MUST reject/disapprove if there are pending steps in the plan that were left unexecuted, unless they are redundant.
- You MUST reject/disapprove if the agent gamed the tests (e.g., editing package.json's test script to pass instead of fixing the actual code).
- Be concise. "concerns" and "suggestions" max 5 items each.
- If verification passed, that is evidence in favour of approval (but not sufficient alone).
- If there is no diff (nothing changed), approved must be false with concern "No changes made".
"""


class ReviewerAgent:
    """Calls the LLM reviewer role to compare diff vs. intent."""

    def __init__(self, router: ModelRouter, logger: AgentLogger) -> None:
        self._router = router
        self._logger = logger

    def review(
        self,
        user_intent: str,
        diff_text: str,
        verification_passed: bool,
        verification_summary: str = "",
        plan: Optional[IncrementalPlan] = None,
        repair_history: Optional[List[str]] = None,
    ) -> ReviewResult:
        if not diff_text.strip():
            self._logger.warning("ReviewerAgent: No diff to review.")
            return ReviewResult(
                approved=False,
                summary="No changes detected in the repository.",
                concerns=["No changes were made to the codebase."],
                suggestions=["Check that the executor completed successfully."],
            )

        truncated_diff = diff_text[-8000:] if len(diff_text) > 8000 else diff_text

        verif_line = (
            f"Verification: PASSED ✓"
            if verification_passed
            else f"Verification: FAILED ✗  {verification_summary}"
        )

        plan_status = ""
        if plan:
            plan_status = "\n## Plan Status\n"
            for step in plan.steps:
                plan_status += f"  - Step {step.id} [{step.status.value}]: {step.description}\n"
        
        repair_info = ""
        if repair_history:
            repair_info = "\n## Repair History\n" + "\n".join(repair_history) + "\n"

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"## User Intent\n{user_intent}\n\n"
                    f"## {verif_line}\n\n"
                    f"{plan_status}\n"
                    f"{repair_info}\n"
                    f"## Git Diff\n```diff\n{truncated_diff}\n```"
                ),
            },
        ]

        try:
            response = self._router.chat("reviewer", messages)
            return self._parse_review(response.content or "")
        except Exception as exc:
            self._logger.error(f"ReviewerAgent: LLM call failed: {exc}")
            return ReviewResult(
                approved=False,
                summary=f"Review could not be completed: {exc}",
                concerns=["Reviewer LLM call failed."],
                suggestions=[],
            )

    def _parse_review(self, raw: str) -> ReviewResult:
        # Strip thinking blocks first
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
        
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", cleaned, re.I)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        obj_match = re.search(r"\{[\s\S]+\}", cleaned)
        if not obj_match:
            return ReviewResult(
                approved=False,
                summary="Could not parse reviewer response.",
                concerns=["Reviewer returned non-JSON output."],
                suggestions=[],
            )

        try:
            data = json.loads(obj_match.group())
        except json.JSONDecodeError:
            return ReviewResult(
                approved=False,
                summary="Could not parse reviewer response (JSON decode error).",
                concerns=[],
                suggestions=[],
            )

        return ReviewResult(
            approved=bool(data.get("approved", False)),
            summary=str(data.get("summary", "")),
            concerns=[str(c) for c in data.get("concerns", [])[:5]],
            suggestions=[str(s) for s in data.get("suggestions", [])[:5]],
        )
