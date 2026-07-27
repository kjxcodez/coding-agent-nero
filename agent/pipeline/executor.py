"""
ToolLoopExecutor — Phase 4, Step 2 of the MODIFY pipeline.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..llm.router import ModelRouter
from ..tools import ToolRegistry
from ..utils.logger import AgentLogger
from .models import IncrementalPlan, PlanStep, StepStatus

EXECUTOR_SYSTEM_PROMPT = """You are NERO's Execution Engine.

You are executing a structured modification plan step by step.

You have access to a full suite of sandboxed software engineering tools.

EXECUTION RULES:
1. Work through the plan steps IN ORDER. Complete step N before starting step N+1.
2. For each step: read only what you need, make minimal targeted edits.
3. Prefer replace_text over write_file for targeted edits.
4. After completing ALL plan steps, output a final message starting with "DONE:" 
   followed by a brief summary of what was changed.
5. If you encounter a step that cannot be completed (file not found, conflicting
   content), mark it as blocked and move to the next step. Never silently skip.
6. Be efficient: do not re-read files you have already read in this session.
7. Never re-plan. Execute the given plan. If something is wrong, note it in DONE:.
"""


class ExecutorError(Exception):
    """Raised when execution fails unrecoverably."""
    pass


class ToolLoopExecutor:
    """Executes a plan via a bounded LLM tool-calling loop."""

    DONE_SIGNAL = "DONE:"

    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        logger: AgentLogger,
        max_iterations: int = 15,
    ) -> None:
        self._router = router
        self._tools = tool_registry
        self._logger = logger
        self._max_iter = max_iterations

    def execute(
        self,
        plan: IncrementalPlan,
        context_summary: str,
        extra_context: str = "",
    ) -> tuple[IncrementalPlan, str]:
        tool_schemas = self._tools.get_openai_schemas()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": EXECUTOR_SYSTEM_PROMPT},
            {"role": "system", "content": context_summary},
            {"role": "system", "content": self._format_plan_block(plan)},
        ]
        if extra_context:
            messages.append({"role": "system", "content": extra_context})

        completion_text = ""
        current_step_idx = 0

        for iteration in range(1, self._max_iter + 1):
            if current_step_idx < len(plan.steps):
                step = plan.steps[current_step_idx]
                if step.status == StepStatus.PENDING:
                    step.mark_in_progress()
                    self._logger.progress(
                        f"Executing step [{step.id}/{len(plan.steps)}]: {step.description}"
                    )

            response = self._router.chat("coder", messages, tools=tool_schemas)

            content = response.content or ""
            if not response.tool_calls:
                if content.strip().startswith(self.DONE_SIGNAL):
                    completion_text = content.strip()
                    self._logger.progress("Executor: DONE signal received.")
                    for s in plan.steps:
                        if s.status == StepStatus.IN_PROGRESS:
                            s.mark_done(completion_text)
                    break
                else:
                    completion_text = content
                    messages.append({"role": "assistant", "content": content})
                    if iteration > 1:
                        break
                    continue

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                tool_result = self._tools.dispatch(tc.name, tc.arguments)
                snippet = tool_result.replace("\n", " ")[:100]
                self._logger.tool(tc.name, tc.arguments, snippet)

                if tc.name in ("write_file", "create_file", "replace_text"):
                    if current_step_idx < len(plan.steps):
                        step = plan.steps[current_step_idx]
                        step.mark_done(f"Wrote via {tc.name}")
                        current_step_idx += 1

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
        else:
            self._logger.warning(
                f"Executor hit max_iterations ({self._max_iter}) without DONE signal. "
                "Plan may be partially complete."
            )
            completion_text = completion_text or "Execution reached max iterations."

        return plan, completion_text

    def _format_plan_block(self, plan: IncrementalPlan) -> str:
        lines = [
            "## Your Modification Plan",
            "",
            f"Goal: {plan.goal}",
            f"Approach: {plan.approach}",
            "",
            "Steps to execute:",
        ]
        for step in plan.steps:
            files_str = (
                f" [{', '.join(step.target_files)}]"
                if step.target_files else ""
            )
            lines.append(f"  Step {step.id}: {step.description}{files_str}")
        lines += [
            "",
            'When ALL steps are complete, output: "DONE: <brief summary of changes>"',
        ]
        return "\n".join(lines)
