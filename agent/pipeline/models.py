"""
Pipeline data structures for the NERO MODIFY workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class PlanStep:
    """One atomic unit of work in a modification plan."""

    id: int
    description: str
    target_files: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    error: str = ""

    def mark_in_progress(self) -> None:
        self.status = StepStatus.IN_PROGRESS

    def mark_done(self, output: str = "") -> None:
        self.status = StepStatus.COMPLETED
        self.output = output

    def mark_failed(self, error: str = "") -> None:
        self.status = StepStatus.FAILED
        self.error = error

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.BLOCKED,
        )


@dataclass
class IncrementalPlan:
    """Structured modification plan produced by IncrementalPlanner."""

    goal: str
    understanding: str
    approach: str
    affected_files: List[str]
    steps: List[PlanStep]
    validation_commands: List[str]
    risks: List[str]
    created_at: str
    model_used: str = ""

    def pending_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def completed_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    def failed_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def is_complete(self) -> bool:
        return all(s.is_terminal for s in self.steps)

    def progress_summary(self) -> str:
        total = len(self.steps)
        done = len(self.completed_steps())
        failed = len(self.failed_steps())
        pending = len(self.pending_steps())
        return f"Plan: {done}/{total} completed, {failed} failed, {pending} pending"

    def format_for_display(self) -> str:
        STATUS_ICON = {
            StepStatus.PENDING: "○",
            StepStatus.IN_PROGRESS: "◉",
            StepStatus.COMPLETED: "✓",
            StepStatus.FAILED: "✗",
            StepStatus.SKIPPED: "–",
            StepStatus.BLOCKED: "⊘",
        }
        lines = [
            f"### Plan: {self.goal}",
            "",
            f"**Approach**: {self.approach}",
            f"**Files**: {', '.join(self.affected_files) or 'TBD'}",
            "",
            "**Steps**:",
        ]
        for step in self.steps:
            icon = STATUS_ICON.get(step.status, "?")
            lines.append(f"  {icon} [{step.id}] {step.description}")
            if step.error:
                lines.append(f"       ↳ ERROR: {step.error[:120]}")
        if self.validation_commands:
            lines += ["", f"**Verification**: `{'`, `'.join(self.validation_commands)}`"]
        if self.risks:
            lines += ["", "**Risks**:"]
            for r in self.risks:
                lines.append(f"  • {r}")
        return "\n".join(lines)


@dataclass
class VerificationResult:
    """Outcome of a verification run (test/lint/build command)."""

    passed: bool
    command: str
    exit_code: int
    stdout: str
    stderr: str
    failed_tests: List[str] = field(default_factory=list)
    error_summary: str = ""
    classification: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def format_for_llm(self, max_output: int = 2000) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Verification [{status}]",
            f"Command: {self.command}",
            f"Exit code: {self.exit_code}",
        ]
        if self.classification:
            lines.append(f"Classification: {self.classification}")
        if self.failed_tests:
            lines.append(f"Failed tests: {', '.join(self.failed_tests[:10])}")
        combined = (self.stdout + "\n" + self.stderr).strip()
        if combined:
            truncated = combined[-max_output:] if len(combined) > max_output else combined
            lines += ["Output:", truncated]
        return "\n".join(lines)


@dataclass
class ReviewResult:
    """Outcome of a reviewer pass comparing diff vs. original intent."""

    approved: bool
    summary: str
    concerns: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def format_for_display(self) -> str:
        verdict = "✓ APPROVED" if self.approved else "⚠ NEEDS WORK"
        lines = [f"### Code Review [{verdict}]", "", self.summary]
        if self.concerns:
            lines += ["", "**Concerns**:"]
            for c in self.concerns:
                lines.append(f"  • {c}")
        if self.suggestions:
            lines += ["", "**Suggestions**:"]
            for s in self.suggestions:
                lines.append(f"  • {s}")
        return "\n".join(lines)


@dataclass
class PipelineOutcome:
    """Top-level result of a completed MODIFY pipeline run."""

    success: bool
    plan: IncrementalPlan
    verification: Optional[VerificationResult] = None
    review: Optional[ReviewResult] = None
    repair_attempts: int = 0
    abort_reason: str = ""

    def format_session_summary(self) -> str:
        status = "✓ Completed" if self.success else "✗ Incomplete"
        lines = [
            f"### Session Summary [{status}]",
            "",
            f"**Goal**: {self.plan.goal}",
            f"**Steps**: {self.plan.progress_summary()}",
        ]
        if self.plan.affected_files:
            lines += ["", "**Files changed**:"]
            for f in self.plan.affected_files:
                lines.append(f"  • `{f}`")
        if self.verification:
            v_status = "passed ✓" if self.verification.passed else "failed ✗"
            lines.append(f"\n**Tests**: {v_status} (exit code {self.verification.exit_code})")
        if self.repair_attempts:
            lines.append(f"**Repair attempts**: {self.repair_attempts}")
        if self.review:
            r_status = "approved ✓" if self.review.approved else "flagged ⚠"
            lines.append(f"**Review**: {r_status} — {self.review.summary[:100]}")
        if self.abort_reason:
            lines.append(f"\n**Abort reason**: {self.abort_reason}")
        return "\n".join(lines)
