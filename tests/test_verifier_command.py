"""
Unit tests for P1.4 fix: --verifier-command propagation.

Tests that:
1. AgentConfig stores verifier_command and skip_verification correctly.
2. build_config() forwards both parameters into the config.
3. PipelineOrchestrator uses config.verifier_command as the sole command.
4. PipelineOrchestrator uses plan.validation_commands when no override is set.
5. skip_verification flag skips the verify stage.
6. The allow-list security layer still applies to the override command.
7. The repair loop reuses the original command (inherited via current_result.command).
"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

from agent.config import AgentConfig
from agent.pipeline.models import (
    IncrementalPlan,
    PlanStep,
    PipelineOutcome,
    ReviewResult,
    StepStatus,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(validation_commands: Optional[List[str]] = None) -> IncrementalPlan:
    return IncrementalPlan(
        goal="Test",
        understanding="",
        approach="",
        affected_files=[],
        steps=[PlanStep(id=1, description="Step 1", status=StepStatus.COMPLETED)],
        validation_commands=validation_commands or [],
        risks=[],
        created_at=datetime.now().isoformat(),
    )


def _make_orchestrator(config: AgentConfig):
    """Build a PipelineOrchestrator with fully-mocked internals."""
    from agent.pipeline.orchestrator import PipelineOrchestrator
    from agent.utils.logger import AgentLogger

    router = MagicMock()
    tools = MagicMock()
    tools.get_openai_schemas.return_value = []
    logger = MagicMock()
    logger.status.return_value.__enter__ = MagicMock(return_value=None)
    logger.status.return_value.__exit__ = MagicMock(return_value=False)

    orch = PipelineOrchestrator(
        config=config,
        router=router,
        tool_registry=tools,
        logger=logger,
    )
    return orch


# ---------------------------------------------------------------------------
# 1. AgentConfig field defaults
# ---------------------------------------------------------------------------

class TestAgentConfigVerifierFields(unittest.TestCase):

    def test_verifier_command_default_is_empty_string(self):
        config = AgentConfig()
        self.assertEqual(config.verifier_command, "")

    def test_skip_verification_default_is_false(self):
        config = AgentConfig()
        self.assertFalse(config.skip_verification)

    def test_verifier_command_can_be_set(self):
        config = AgentConfig()
        config.verifier_command = "npm test"
        self.assertEqual(config.verifier_command, "npm test")

    def test_skip_verification_can_be_set(self):
        config = AgentConfig()
        config.skip_verification = True
        self.assertTrue(config.skip_verification)

    def test_with_single_model_preserves_verifier_fields(self):
        config = AgentConfig.with_single_model("gpt-4")
        self.assertEqual(config.verifier_command, "")
        self.assertFalse(config.skip_verification)


# ---------------------------------------------------------------------------
# 2. build_config() propagation
# ---------------------------------------------------------------------------

class TestBuildConfigPropagation(unittest.TestCase):

    def test_build_config_without_verifier_command_leaves_empty(self):
        from agent.main import build_config
        config = build_config()
        self.assertEqual(config.verifier_command, "")
        self.assertFalse(config.skip_verification)

    def test_build_config_with_verifier_command_sets_field(self):
        from agent.main import build_config
        config = build_config(verifier_command="pytest")
        self.assertEqual(config.verifier_command, "pytest")

    def test_build_config_with_npm_test_command(self):
        from agent.main import build_config
        config = build_config(verifier_command="npm test")
        self.assertEqual(config.verifier_command, "npm test")

    def test_build_config_skip_verification_propagated(self):
        from agent.main import build_config
        config = build_config(skip_verification=True)
        self.assertTrue(config.skip_verification)

    def test_build_config_empty_verifier_command_not_set(self):
        """Passing None (the default) must leave verifier_command empty."""
        from agent.main import build_config
        config = build_config(verifier_command=None)
        self.assertEqual(config.verifier_command, "")

    def test_build_config_with_model_still_propagates_verifier_command(self):
        """with_single_model path must also carry the verifier_command."""
        from agent.main import build_config
        config = build_config(model="gpt-4", verifier_command="pytest")
        self.assertEqual(config.verifier_command, "pytest")


# ---------------------------------------------------------------------------
# 3. Orchestrator verification stage routing
# ---------------------------------------------------------------------------

class TestOrchestratorVerifierRouting(unittest.TestCase):
    """
    Tests that PipelineOrchestrator.run() calls verifier.verify() with the
    correct command list depending on config state.
    """

    def _run_orch_verify_stage(self, config: AgentConfig, plan: IncrementalPlan):
        """
        Invoke just the verify stage by mocking planner and executor to
        return immediately, then capturing the verify() call arguments.
        """
        orch = _make_orchestrator(config)

        # Mock planner to return our plan
        orch._planner = MagicMock()
        orch._planner.plan.return_value = plan

        # Mock executor to return plan unchanged
        orch._executor = MagicMock()
        orch._executor.execute.return_value = (plan, "DONE: ok")

        # Mock reviewer to approve everything
        orch._reviewer = MagicMock()
        orch._reviewer.review.return_value = ReviewResult(
            approved=True, summary="ok"
        )

        # Track verifier calls
        verify_calls = []
        def capture_verify(repo_path, commands=None):
            verify_calls.append({"repo_path": repo_path, "commands": commands})
            return VerificationResult(
                passed=True, command=str(commands), exit_code=0,
                stdout="passed", stderr=""
            )
        orch._verifier = MagicMock()
        orch._verifier.verify.side_effect = capture_verify

        # Mock repo_context
        repo_ctx = MagicMock()
        repo_ctx.repo_path = "/fake/repo"
        repo_ctx.format_context_summary.return_value = "context"

        # Mock memory
        memory = MagicMock()

        orch.run(
            user_request="test",
            repo_context=repo_ctx,
            memory=memory,
            require_confirmation=False,
        )
        return verify_calls

    # Scenario 1 — no override: uses plan.validation_commands
    def test_scenario1_no_override_uses_plan_commands(self):
        config = AgentConfig()
        plan = _make_plan(validation_commands=["pytest"])
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["commands"], ["pytest"])

    # Scenario 2 — npm test override
    def test_scenario2_npm_test_override(self):
        config = AgentConfig()
        config.verifier_command = "npm test"
        plan = _make_plan(validation_commands=["pytest"])  # plan says pytest
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(len(calls), 1)
        # Must use npm test, NOT pytest from the plan
        self.assertEqual(calls[0]["commands"], ["npm test"])

    # Scenario 3 — pytest override
    def test_scenario3_pytest_override(self):
        config = AgentConfig()
        config.verifier_command = "pytest"
        plan = _make_plan(validation_commands=[])
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(calls[0]["commands"], ["pytest"])

    # Scenario 4 — override takes priority over plan commands
    def test_scenario4_override_beats_plan_commands(self):
        config = AgentConfig()
        config.verifier_command = "npm run test"
        plan = _make_plan(validation_commands=["cargo test", "go test"])
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(calls[0]["commands"], ["npm run test"])

    # Scenario 5 — skip_verification
    def test_scenario5_skip_verification_passes_empty_commands(self):
        config = AgentConfig()
        config.skip_verification = True
        plan = _make_plan(validation_commands=["pytest"])
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["commands"], [])

    # Scenario 6 — no override, no plan commands → auto-detect (commands=None)
    def test_scenario6_no_override_no_plan_commands_triggers_auto_detect(self):
        config = AgentConfig()
        plan = _make_plan(validation_commands=[])
        calls = self._run_orch_verify_stage(config, plan)
        self.assertEqual(len(calls), 1)
        # Empty list converted to None (via `plan.validation_commands or None`)
        self.assertIsNone(calls[0]["commands"])


# ---------------------------------------------------------------------------
# 4. Allow-list security check still applies
# ---------------------------------------------------------------------------

class TestVerifierAllowList(unittest.TestCase):
    """The allow-list must reject commands even when supplied via --verifier-command."""

    def test_allowed_command_passes_allow_list(self):
        from agent.pipeline.verifier import VerificationEngine
        from agent.utils.logger import AgentLogger
        config = AgentConfig()
        logger = MagicMock()
        engine = VerificationEngine(config, logger)
        # pytest is on the allow-list
        self.assertTrue(engine._is_allowed("pytest"))
        self.assertTrue(engine._is_allowed("npm test"))

    def test_disallowed_command_rejected_even_from_cli(self):
        """A dangerous command supplied via --verifier-command must still be rejected."""
        from agent.pipeline.verifier import VerificationEngine
        config = AgentConfig()
        config.verifier_command = "rm -rf /"
        logger = MagicMock()
        engine = VerificationEngine(config, logger)
        result = engine._run_one("rm -rf /", "/tmp")
        self.assertFalse(result.passed)
        self.assertIn("not in allow-list", result.stderr)

    def test_custom_script_rejected_by_allow_list(self):
        """./gradlew test is not on the allow-list and must be rejected."""
        from agent.pipeline.verifier import VerificationEngine
        config = AgentConfig()
        logger = MagicMock()
        engine = VerificationEngine(config, logger)
        self.assertFalse(engine._is_allowed("./gradlew test"))


# ---------------------------------------------------------------------------
# 5. Repair loop inherits command from current_result.command
# ---------------------------------------------------------------------------

class TestRepairLoopCommandInheritance(unittest.TestCase):

    def test_repair_loop_uses_command_from_initial_verification(self):
        """
        The repair loop calls verifier.verify(commands=[current_result.command]).
        When orchestrator sets the initial command from config.verifier_command,
        the repair loop must re-use that same command — not fall back to auto-detect.
        """
        from agent.pipeline.repair import RepairController

        failing = VerificationResult(
            passed=False,
            command="npm test",      # ← this is what orchestrator set
            exit_code=1,
            stdout="1 failing",
            stderr="",
            error_summary="test_foo failed",
        )
        passing = VerificationResult(
            passed=True,
            command="npm test",
            exit_code=0,
            stdout="1 passing",
            stderr="",
        )

        executor = MagicMock()
        executor._tools = MagicMock()
        executor._tools.memory = MagicMock()
        plan = _make_plan(["npm test"])
        plan.steps[0].status = StepStatus.PENDING
        executor.execute.return_value = (plan, "DONE")

        verifier = MagicMock()
        verifier.verify.return_value = passing

        logger = MagicMock()
        repair = RepairController(executor, verifier, logger, max_attempts=2)

        repair.repair(
            plan=plan,
            failing_result=failing,
            repo_path="/fake/repo",
            context_summary="ctx",
        )

        # Verifier must be called with the same command as the failing result
        verifier.verify.assert_called_once_with(
            repo_path="/fake/repo",
            commands=["npm test"],
        )


if __name__ == "__main__":
    unittest.main()
