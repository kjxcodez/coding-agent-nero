"""
RepairController — Phase 4, Step 4 of the MODIFY pipeline.
"""

from __future__ import annotations

from typing import List
from ..utils.logger import AgentLogger
from .executor import ToolLoopExecutor
from .models import IncrementalPlan, VerificationResult
from .verifier import VerificationEngine


class RepairController:
    """Retry executor + verifier loop until tests pass or attempts are exhausted."""

    def __init__(
        self,
        executor: ToolLoopExecutor,
        verifier: VerificationEngine,
        logger: AgentLogger,
        max_attempts: int = 3,
    ) -> None:
        self._executor = executor
        self._verifier = verifier
        self._logger = logger
        self._max_attempts = max_attempts

    def repair(
        self,
        plan: IncrementalPlan,
        failing_result: VerificationResult,
        repo_path: str,
        context_summary: str,
    ) -> tuple[VerificationResult, int, List[str]]:
        current_result = failing_result
        attempts = 0
        history: List[str] = []

        if self._executor and self._executor._tools and self._executor._tools.memory:
            self._executor._tools.memory.in_repair_loop = True

        try:
            for attempt in range(1, self._max_attempts + 1):
                self._logger.progress(
                    f"Repair attempt {attempt}/{self._max_attempts} "
                    f"(command: {current_result.command})"
                )

                error_context = self._format_error_context(current_result, attempt)
                history.append(
                    f"Attempt {attempt} Context: Verification '{current_result.command}' failed (exit code {current_result.exit_code}). "
                    f"Error Summary: {current_result.error_summary[:400]}"
                )

                plan, _ = self._executor.execute(
                    plan=plan,
                    context_summary=context_summary,
                    extra_context=error_context,
                )
                attempts += 1

                current_result = self._verifier.verify(
                    repo_path=repo_path,
                    commands=[current_result.command],
                )

                if current_result.passed:
                    self._logger.progress(
                        f"Repair succeeded on attempt {attempt}. Tests now passing."
                    )
                    history.append(f"Attempt {attempt} Result: SUCCESS. Tests passed.")
                    return current_result, attempts, history

                self._logger.warning(
                    f"Repair attempt {attempt} did not fix the failures. "
                    f"Exit code: {current_result.exit_code}"
                )
                history.append(f"Attempt {attempt} Result: FAILED. Exit code {current_result.exit_code}.")

            self._logger.error(
                f"All {self._max_attempts} repair attempts failed. "
                "Returning last verification result."
            )
            return current_result, attempts, history
        finally:
            if self._executor and self._executor._tools and self._executor._tools.memory:
                self._executor._tools.memory.in_repair_loop = False

    @staticmethod
    def _format_error_context(result: VerificationResult, attempt: int) -> str:
        lines = [
            f"## Repair Context (Attempt {attempt})",
            "",
            f"The verification command `{result.command}` FAILED with exit code {result.exit_code}.",
            "",
        ]
        if result.failed_tests:
            lines += [
                "Failed tests:",
                *[f"  • {t}" for t in result.failed_tests[:10]],
                "",
            ]
        if result.error_summary:
            lines += ["Error summary:", result.error_summary[:2000], ""]

        lines += [
            "Your task: Fix the failing tests WITHOUT changing the intended functionality.",
            "Focus on the specific error messages above.",
            'When fixed, output: "DONE: <what you changed to fix the tests>"',
        ]
        return "\n".join(lines)
