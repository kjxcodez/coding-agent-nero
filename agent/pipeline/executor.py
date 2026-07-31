"""
ToolLoopExecutor — Phase 4, Step 2 of the MODIFY pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ..llm.router import ModelRouter
from ..tools import ToolRegistry
from ..utils.logger import AgentLogger
from .models import IncrementalPlan, StepStatus

EXECUTOR_SYSTEM_PROMPT = """You are NERO's Execution Engine.

You are executing a structured modification plan step by step.

You have access to a full suite of sandboxed software engineering tools.

EXECUTION RULES:
1. Work through the plan steps IN ORDER. Complete step N before starting step N+1.
2. For each step: read only what you need, make minimal targeted edits.
3. Prefer replace_text over write_file for targeted edits.
4. After completing each individual step, output a SHORT text message:
   "STEP N DONE: <one-line summary>" where N is the step number.
   Then immediately continue to the next step using tools — do not wait.
5. After completing ALL plan steps, output a final message starting with "DONE:"
   followed by a brief summary of what was changed.
6. If you encounter a step that cannot be completed (file not found, conflicting
   content), output "STEP N BLOCKED: <reason>" and move to the next step.
7. Be efficient: do not re-read files you have already read in this session.
   If you already received the content of a file, DO NOT read it again — use it.
8. Never re-plan. Execute the given plan. If something is wrong, note it in DONE:.
9. NEVER use shell commands (ls, find, grep) for file exploration. Use list_files
   and read_file tools instead.
"""

# Regex that matches "STEP N DONE:" or "STEP N BLOCKED:" in LLM text output.
# N is 1-indexed and matches the plan step id.
_STEP_SIGNAL_RE = re.compile(
    r"STEP\s+(\d+)\s+(DONE|BLOCKED)\s*:",
    re.IGNORECASE,
)


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
        tool_schemas = [s for s in self._tools.get_openai_schemas() if s["function"]["name"] != "clone_repo"]

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": EXECUTOR_SYSTEM_PROMPT},
            {"role": "system", "content": context_summary},
            {"role": "system", "content": self._format_plan_block(plan)},
        ]
        if extra_context:
            messages.append({"role": "system", "content": extra_context})

        completion_text = ""
        # Start from the first non-terminal step so that when the repair loop
        # re-calls execute() on a partially-completed plan, we don't re-announce
        # already-completed steps. Within the loop, steps advance only via
        # explicit LLM "STEP N DONE:" signals.
        current_step_idx = next(
            (i for i, s in enumerate(plan.steps) if not s.is_terminal),
            len(plan.steps),  # all done → points past end, loop exits cleanly
        )
        # Repetition guard: track last N tool calls to detect infinite loops
        _last_calls: list = []  # stores (tool_name, args_json) tuples

        for iteration in range(1, self._max_iter + 1):
            if current_step_idx < len(plan.steps):
                step = plan.steps[current_step_idx]
                if step.status == StepStatus.PENDING:
                    step.mark_in_progress()
                    self._logger.progress(f"Executing step [{step.id}/{len(plan.steps)}]: {step.description}")

            response = self._router.chat("coder", messages, tools=tool_schemas)

            content = response.content or ""
            if not response.tool_calls:
                if content.strip().startswith(self.DONE_SIGNAL):
                    completion_text = content.strip()
                    self._logger.progress("Executor: DONE signal received.")
                    # Mark any step still IN_PROGRESS as done (safety fallback
                    # for models that skip individual STEP N DONE signals).
                    for s in plan.steps:
                        if s.status == StepStatus.IN_PROGRESS:
                            s.mark_done(completion_text)
                    break
                else:
                    # Check for individual step completion signals even in
                    # non-tool-call turns (the LLM may emit text between tools).
                    current_step_idx = self._apply_step_signals(content, plan, current_step_idx)
                    completion_text = content
                    messages.append({"role": "assistant", "content": content})
                    if iteration > 1:
                        break
                    continue

            # Apply per-step signals from any text content returned alongside
            # tool calls (the LLM may narrate progress mid-execution).
            if content:
                current_step_idx = self._apply_step_signals(content, plan, current_step_idx)

            if response.assistant_message:
                messages.append(response.assistant_message)
            else:
                messages.append(
                    {
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
                    }
                )

            for tc in response.tool_calls:
                # --- Repetition guard ---
                call_sig = (tc.name, json.dumps(tc.arguments, sort_keys=True))
                _last_calls.append(call_sig)
                if len(_last_calls) > 6:
                    _last_calls.pop(0)
                # If the same call appears 3 times in the last 6, inject a hint
                if _last_calls.count(call_sig) >= 3:
                    self._logger.warning(
                        f"Loop detected: '{tc.name}' called with identical args {tc.arguments} "
                        f"3+ times. Injecting hint to proceed."
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": (
                                f"[LOOP DETECTED] You have already received the result of "
                                f"'{tc.name}' with these arguments. Stop calling this tool again. "
                                f"Use the content you already received and proceed to the next action."
                            ),
                        }
                    )
                    continue
                # --- End repetition guard ---

                tool_result = self._tools.dispatch(tc.name, tc.arguments)
                snippet = tool_result.replace("\n", " ")[:100]
                self._logger.tool(tc.name, tc.arguments, snippet)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": tool_result,
                    }
                )
        else:
            self._logger.warning(
                f"Executor hit max_iterations ({self._max_iter}) without DONE signal. Plan may be partially complete."
            )
            completion_text = completion_text or "Execution reached max iterations."

        return plan, completion_text

    def _apply_step_signals(
        self,
        text: str,
        plan: IncrementalPlan,
        current_step_idx: int,
    ) -> int:
        """
        Scan the LLM's text output for STEP N DONE / STEP N BLOCKED signals.
        Advance current_step_idx and update step statuses accordingly.

        The LLM is instructed to emit "STEP N DONE: <summary>" after completing
        each plan step. This is the ONLY mechanism that advances the step pointer
        — not file writes, not tool call counts.

        Returns the updated current_step_idx.
        """
        for match in _STEP_SIGNAL_RE.finditer(text):
            step_num = int(match.group(1))
            signal_type = match.group(2).upper()

            # Find the step by id (1-indexed, matches the plan step id field).
            matching = [s for s in plan.steps if s.id == step_num]
            if not matching:
                continue
            step = matching[0]

            if step.is_terminal:
                # Already resolved; don't overwrite.
                continue

            if signal_type == "DONE":
                step.mark_done(text[:200])
                self._logger.progress(f"Step [{step_num}/{len(plan.steps)}] completed.")
            elif signal_type == "BLOCKED":
                step.mark_failed(f"Blocked: {text[:200]}")
                self._logger.warning(f"Step [{step_num}/{len(plan.steps)}] blocked.")

            # Advance current_step_idx to the step AFTER the one just resolved,
            # but only if we're currently on or before this step.
            step_list_idx = next((i for i, s in enumerate(plan.steps) if s.id == step_num), None)
            if step_list_idx is not None and current_step_idx <= step_list_idx:
                current_step_idx = step_list_idx + 1

        return current_step_idx

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
            files_str = f" [{', '.join(step.target_files)}]" if step.target_files else ""
            lines.append(f"  Step {step.id}: {step.description}{files_str}")
        lines += [
            "",
            'After each step, output: "STEP N DONE: <summary>" (where N is the step number).',
            'When ALL steps are complete, output: "DONE: <brief summary of changes>"',
        ]
        return "\n".join(lines)
