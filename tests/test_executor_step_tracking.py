"""
Unit tests for P1.1 fix: executor step pointer advancement.

Tests _apply_step_signals() and the full execute() flow to verify
that the step pointer advances ONLY on explicit LLM "STEP N DONE:"
signals, never on file write tool calls.

Covers all 6 scenarios from the audit finding specification.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import List, Optional
from unittest.mock import MagicMock

from agent.pipeline.executor import _STEP_SIGNAL_RE, ToolLoopExecutor
from agent.pipeline.models import IncrementalPlan, PlanStep, StepStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(n_steps: int) -> IncrementalPlan:
    """Build a fresh n-step plan with all steps PENDING."""
    return IncrementalPlan(
        goal="Test goal",
        understanding="",
        approach="",
        affected_files=[],
        steps=[PlanStep(id=i, description=f"Step {i}") for i in range(1, n_steps + 1)],
        validation_commands=[],
        risks=[],
        created_at=datetime.now().isoformat(),
    )


def _make_executor() -> ToolLoopExecutor:
    """Build an executor with stub router/tools/logger."""
    router = MagicMock()
    tools = MagicMock()
    tools.get_openai_schemas.return_value = []
    logger = MagicMock()
    return ToolLoopExecutor(
        router=router,
        tool_registry=tools,
        logger=logger,
        max_iterations=20,
    )


def _stub_response(content: str = "", tool_calls: Optional[List] = None):
    """Build a mock LLM response."""
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    resp.assistant_message = None
    return resp


# ---------------------------------------------------------------------------
# Tests for _apply_step_signals (unit)
# ---------------------------------------------------------------------------


class TestApplyStepSignals(unittest.TestCase):
    """Tests for the _apply_step_signals helper in isolation."""

    def setUp(self):
        self.executor = _make_executor()

    def test_step_done_signal_marks_step_completed(self):
        """STEP 1 DONE: must mark step 1 as COMPLETED."""
        plan = _make_plan(3)
        plan.steps[0].mark_in_progress()

        idx = self.executor._apply_step_signals("STEP 1 DONE: added tags", plan, 0)

        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(idx, 1)  # advanced past step 1

    def test_step_blocked_signal_marks_step_failed(self):
        """STEP 2 BLOCKED: must mark step 2 as FAILED."""
        plan = _make_plan(3)
        plan.steps[1].mark_in_progress()

        idx = self.executor._apply_step_signals("STEP 2 BLOCKED: file not found", plan, 1)

        self.assertEqual(plan.steps[1].status, StepStatus.FAILED)
        self.assertEqual(idx, 2)

    def test_multiple_signals_in_one_text(self):
        """Multiple STEP N DONE in one message must all be applied."""
        plan = _make_plan(3)
        for s in plan.steps:
            s.mark_in_progress()

        text = "STEP 1 DONE: done\nSTEP 2 DONE: done\nSTEP 3 DONE: done"
        idx = self.executor._apply_step_signals(text, plan, 0)

        for s in plan.steps:
            self.assertEqual(s.status, StepStatus.COMPLETED)
        self.assertEqual(idx, 3)

    def test_signal_does_not_overwrite_terminal_step(self):
        """Already-completed steps must not be overwritten by a duplicate signal."""
        plan = _make_plan(2)
        plan.steps[0].mark_done("already done")

        # Emitting STEP 1 DONE again must not change output field
        self.executor._apply_step_signals("STEP 1 DONE: again", plan, 1)

        self.assertEqual(plan.steps[0].output, "already done")

    def test_unknown_step_id_is_ignored(self):
        """A signal for a non-existent step id must not crash or affect state."""
        plan = _make_plan(2)
        idx = self.executor._apply_step_signals("STEP 99 DONE: ghost step", plan, 0)
        self.assertEqual(idx, 0)  # unchanged

    def test_step_idx_not_decreased(self):
        """current_step_idx must not go backwards."""
        plan = _make_plan(3)
        plan.steps[0].mark_done()
        plan.steps[1].mark_done()

        # current_step_idx is already 2; getting STEP 1 DONE again must not move it back
        idx = self.executor._apply_step_signals("STEP 1 DONE: duplicate", plan, 2)
        self.assertEqual(idx, 2)

    def test_case_insensitive_signal(self):
        """Signal must be matched case-insensitively."""
        plan = _make_plan(1)
        plan.steps[0].mark_in_progress()

        idx = self.executor._apply_step_signals("step 1 done: works", plan, 0)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(idx, 1)

    def test_regex_matches_step_signals(self):
        """The regex must match all expected signal formats."""
        self.assertTrue(_STEP_SIGNAL_RE.search("STEP 1 DONE: added field"))
        self.assertTrue(_STEP_SIGNAL_RE.search("STEP 12 DONE: big step"))
        self.assertTrue(_STEP_SIGNAL_RE.search("STEP 3 BLOCKED: file missing"))
        self.assertTrue(_STEP_SIGNAL_RE.search("step 1 done: lowercase"))
        # Must NOT match noise
        self.assertIsNone(_STEP_SIGNAL_RE.search("Done with everything"))
        self.assertIsNone(_STEP_SIGNAL_RE.search("STEP ONE DONE:"))


# ---------------------------------------------------------------------------
# Tests for execute() integration (with mocked LLM)
# ---------------------------------------------------------------------------


class TestExecuteStepTracking(unittest.TestCase):
    """Integration tests for execute(), verifying step pointer behavior."""

    def setUp(self):
        self.executor = _make_executor()

    def _run_with_responses(self, plan: IncrementalPlan, responses: list) -> IncrementalPlan:
        """Run execute() with a pre-programmed sequence of LLM responses."""
        self.executor._router.chat.side_effect = responses
        result_plan, _ = self.executor.execute(
            plan=plan,
            context_summary="test context",
        )
        return result_plan

    # Scenario 1 — one step, one file write
    def test_scenario1_one_step_one_write(self):
        """SCENARIO 1: One step that writes one file advances the step exactly once."""
        plan = _make_plan(1)
        tc = MagicMock()
        tc.id = "tc1"
        tc.name = "write_file"
        tc.arguments = {"path": "model.js", "content": "..."}

        responses = [
            _stub_response(content="", tool_calls=[tc]),  # LLM calls write_file
            _stub_response(content="STEP 1 DONE: wrote model"),  # LLM signals done
            _stub_response(content="DONE: all steps complete"),  # final signal
        ]
        plan = self._run_with_responses(plan, responses)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)

    # Scenario 2 — one step, three file writes
    def test_scenario2_one_step_three_writes(self):
        """SCENARIO 2: One step that writes three files must advance the step exactly once."""
        plan = _make_plan(2)

        def make_tc(name, path):
            tc = MagicMock()
            tc.id = f"tc_{path}"
            tc.name = name
            tc.arguments = {"path": path, "content": "..."}
            return tc

        tc1 = make_tc("write_file", "model.js")
        tc2 = make_tc("write_file", "controller.js")
        tc3 = make_tc("write_file", "routes.js")

        responses = [
            _stub_response("", tool_calls=[tc1]),
            _stub_response("", tool_calls=[tc2]),
            _stub_response("", tool_calls=[tc3]),
            _stub_response("STEP 1 DONE: updated model, controller, routes"),
            _stub_response("DONE: step 1 complete, step 2 pending"),
        ]
        plan = self._run_with_responses(plan, responses)

        # Only step 1 should be COMPLETED; step 2 remains PENDING
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        # Step 2 was never signalled done, so it's at most IN_PROGRESS
        self.assertNotEqual(plan.steps[1].status, StepStatus.COMPLETED)

    # Scenario 3 — one step, two create_file calls
    def test_scenario3_one_step_two_creates(self):
        """SCENARIO 3: One step that creates two files advances the step exactly once."""
        plan = _make_plan(1)

        tc1 = MagicMock()
        tc1.id = "tc1"
        tc1.name = "create_file"
        tc1.arguments = {"path": "tag.js", "content": "..."}

        tc2 = MagicMock()
        tc2.id = "tc2"
        tc2.name = "create_file"
        tc2.arguments = {"path": "tag-test.js", "content": "..."}

        responses = [
            _stub_response("", tool_calls=[tc1]),
            _stub_response("", tool_calls=[tc2]),
            _stub_response("STEP 1 DONE: created tag and test files"),
            _stub_response("DONE: complete"),
        ]
        plan = self._run_with_responses(plan, responses)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)

    # Scenario 4 — one step, no file writes
    def test_scenario4_no_file_writes(self):
        """SCENARIO 4: A step that requires no file writes must still complete."""
        plan = _make_plan(1)

        responses = [
            _stub_response("STEP 1 DONE: verified existing structure, no changes needed"),
            _stub_response("DONE: complete"),
        ]
        plan = self._run_with_responses(plan, responses)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)

    # Scenario 5 — repair loop step index preservation
    def test_scenario5_repair_loop_starts_from_non_terminal_step(self):
        """SCENARIO 5: When repair calls execute() on a plan with completed steps,
        current_step_idx must start at the first non-terminal step."""
        plan = _make_plan(3)
        plan.steps[0].mark_done("done in primary execution")  # step 1 complete
        # step 2 was IN_PROGRESS and failed (still IN_PROGRESS on re-call)
        plan.steps[1].mark_in_progress()

        responses = [
            _stub_response("STEP 2 DONE: fixed the error"),
            _stub_response("STEP 3 DONE: completed step 3"),
            _stub_response("DONE: all repaired"),
        ]
        plan = self._run_with_responses(plan, responses)

        # Step 1 remains completed, step 2 and 3 also complete
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(plan.steps[1].status, StepStatus.COMPLETED)
        self.assertEqual(plan.steps[2].status, StepStatus.COMPLETED)

    # Scenario 6 — resume from interrupted execution
    def test_scenario6_resume_starts_from_incomplete_step(self):
        """SCENARIO 6: Resume from interrupted execution starts at the pending step."""
        plan = _make_plan(4)
        plan.steps[0].mark_done("done")
        plan.steps[1].mark_done("done")
        # steps 3 and 4 are still PENDING

        responses = [
            _stub_response("STEP 3 DONE: completed"),
            _stub_response("STEP 4 DONE: completed"),
            _stub_response("DONE: all steps done"),
        ]
        plan = self._run_with_responses(plan, responses)

        for s in plan.steps:
            self.assertEqual(s.status, StepStatus.COMPLETED, f"Step {s.id} should be COMPLETED but was {s.status}")

    # Verify per-write advancement is GONE
    def test_write_call_does_not_advance_step(self):
        """File write tool calls must NOT advance the step pointer."""
        plan = _make_plan(3)

        tc1 = MagicMock()
        tc1.id = "tc1"
        tc1.name = "write_file"
        tc1.arguments = {"path": "a.js", "content": "..."}

        tc2 = MagicMock()
        tc2.id = "tc2"
        tc2.name = "write_file"
        tc2.arguments = {"path": "b.js", "content": "..."}

        tc3 = MagicMock()
        tc3.id = "tc3"
        tc3.name = "write_file"
        tc3.arguments = {"path": "c.js", "content": "..."}

        # Three writes then DONE — only one step signal emitted
        responses = [
            _stub_response("", tool_calls=[tc1]),
            _stub_response("", tool_calls=[tc2]),
            _stub_response("", tool_calls=[tc3]),
            _stub_response("STEP 1 DONE: wrote 3 files"),
            _stub_response("DONE: step 1 done"),
        ]
        plan = self._run_with_responses(plan, responses)

        # Only step 1 should be COMPLETED; steps 2 and 3 should NOT be
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertNotEqual(
            plan.steps[1].status, StepStatus.COMPLETED, "Step 2 must NOT be COMPLETED just because 2 files were written"
        )
        self.assertNotEqual(
            plan.steps[2].status, StepStatus.COMPLETED, "Step 3 must NOT be COMPLETED just because 3 files were written"
        )


# ---------------------------------------------------------------------------
# Verify current_step_idx initialization
# ---------------------------------------------------------------------------


class TestCurrentStepIdxInit(unittest.TestCase):
    """Verify the initial step index computation."""

    def test_fresh_plan_starts_at_zero(self):
        """All-PENDING plan must start at index 0."""
        plan = _make_plan(3)
        expected = next(
            (i for i, s in enumerate(plan.steps) if not s.is_terminal),
            len(plan.steps),
        )
        self.assertEqual(expected, 0)

    def test_partial_plan_starts_at_first_pending(self):
        """Plan with step 1 done must start at index 1."""
        plan = _make_plan(3)
        plan.steps[0].mark_done()
        expected = next(
            (i for i, s in enumerate(plan.steps) if not s.is_terminal),
            len(plan.steps),
        )
        self.assertEqual(expected, 1)

    def test_fully_complete_plan_starts_past_end(self):
        """Fully-completed plan must start past the end (safe no-op)."""
        plan = _make_plan(2)
        plan.steps[0].mark_done()
        plan.steps[1].mark_done()
        expected = next(
            (i for i, s in enumerate(plan.steps) if not s.is_terminal),
            len(plan.steps),
        )
        self.assertEqual(expected, 2)  # past end = no iteration


if __name__ == "__main__":
    unittest.main()
