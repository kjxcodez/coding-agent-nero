"""
PipelineOrchestrator — the single entry point for the MODIFY pipeline.
Manages the complete Planner → Executor → Verifier → Repair → Reviewer lifecycle.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from ..config import AgentConfig
from ..intelligence.context import RepositoryContext
from ..llm.router import ModelRouter
from ..memory.session import SessionMemory
from ..tools import ToolRegistry
from ..utils.logger import AgentLogger
from .executor import ToolLoopExecutor
from .models import IncrementalPlan, PipelineOutcome
from .planner import IncrementalPlanner, PlannerError
from .repair import RepairController
from .reviewer import ReviewerAgent
from .verifier import VerificationEngine


class PipelineOrchestrator:
    """Wires Planner → Executor → Verifier → Repair → Reviewer into a single call."""

    def __init__(
        self,
        config: AgentConfig,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        logger: AgentLogger,
    ) -> None:
        self._config = config
        self._router = router
        self._tools = tool_registry
        self._logger = logger

        self._planner  = IncrementalPlanner(router)
        self._executor = ToolLoopExecutor(
            router=router,
            tool_registry=tool_registry,
            logger=logger,
            max_iterations=config.max_iterations,
        )
        self._verifier = VerificationEngine(config, logger)
        self._repair   = RepairController(
            executor=self._executor,
            verifier=self._verifier,
            logger=logger,
            max_attempts=config.max_repair_attempts,
        )
        self._reviewer = ReviewerAgent(router, logger)

    def run(
        self,
        user_request: str,
        repo_context: RepositoryContext,
        memory: SessionMemory,
        require_confirmation: bool = True,
    ) -> PipelineOutcome:
        repo_path = repo_context.repo_path
        context_summary = repo_context.format_context_summary()

        # ── Stage 1: Plan ────────────────────────────────────────────────
        with self._logger.status("Phase 1/4: Planning..."):
            try:
                plan = self._planner.plan(user_request, repo_context)
            except PlannerError as exc:
                self._logger.error(f"Planning failed: {exc}")
                return self._abort("Planning failed", str(exc), user_request)

        self._logger.markdown(plan.format_for_display())

        if require_confirmation and self._needs_confirmation(plan):
            if not self._ask_confirmation(plan):
                return self._abort(
                    "User cancelled",
                    "User declined to proceed with the plan.",
                    user_request,
                    plan=plan,
                )

        # ── Stage 2: Execute ─────────────────────────────────────────────
        with self._logger.status("Phase 2/4: Executing..."):
            try:
                plan, completion_text = self._executor.execute(
                    plan=plan,
                    context_summary=context_summary,
                )
            except Exception as exc:
                self._logger.error(f"Execution failed: {exc}")
                return self._abort("Execution error", str(exc), user_request, plan=plan)

        # ── Stage 3: Verify ──────────────────────────────────────────────
        with self._logger.status("Phase 3/4: Verifying..."):
            verification = self._verifier.verify(
                repo_path=repo_path,
                commands=plan.validation_commands or None,
            )

            repair_attempts = 0
            if not verification.passed:
                self._logger.warning(
                    f"Verification failed (exit code {verification.exit_code}). "
                    f"Starting repair loop..."
                )
                verification, repair_attempts = self._repair.repair(
                    plan=plan,
                    failing_result=verification,
                    repo_path=repo_path,
                    context_summary=context_summary,
                )

        # ── Stage 4: Review ──────────────────────────────────────────────
        with self._logger.status("Phase 4/4: Reviewing..."):
            diff_text = self._get_diff(repo_path)
            review = self._reviewer.review(
                user_intent=user_request,
                diff_text=diff_text,
                verification_passed=verification.passed,
                verification_summary=verification.error_summary,
            )

        self._logger.markdown(review.format_for_display())

        outcome = PipelineOutcome(
            success=verification.passed and review.approved,
            plan=plan,
            verification=verification,
            review=review,
            repair_attempts=repair_attempts,
        )
        return outcome

    def _needs_confirmation(self, plan: IncrementalPlan) -> bool:
        if len(plan.steps) >= 3:
            return True
        if len(plan.affected_files) > 3:
            return True
        destructive = ("delete", "remove", "drop", "truncate", "reset", "revert")
        for step in plan.steps:
            if any(kw in step.description.lower() for kw in destructive):
                return True
        return False

    def _ask_confirmation(self, plan: IncrementalPlan) -> bool:
        try:
            answer = input(
                f"\n{len(plan.steps)} steps · {len(plan.affected_files)} files · "
                "Proceed? [y/N] "
            ).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def _get_diff(self, repo_path: str) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            diff = result.stdout.strip()
            if not diff:
                result2 = subprocess.run(
                    ["git", "diff", "--cached"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                diff = result2.stdout.strip()
            return diff
        except Exception:
            return ""

    def _abort(
        self,
        reason: str,
        detail: str,
        user_request: str,
        plan: Optional[IncrementalPlan] = None,
    ) -> PipelineOutcome:
        if plan is None:
            from datetime import datetime
            from .models import PlanStep
            plan = IncrementalPlan(
                goal=user_request[:100],
                understanding="",
                approach="",
                affected_files=[],
                steps=[PlanStep(id=1, description="(aborted before execution)")],
                validation_commands=[],
                risks=[],
                created_at=datetime.now().isoformat(),
            )
        return PipelineOutcome(
            success=False,
            plan=plan,
            abort_reason=f"{reason}: {detail}",
        )
