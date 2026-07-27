"""
Unit tests for NERO WorkingMemory, RepositoryContext, Tool Caching, Intent Router,
and Phase 4 Pipeline data structures and components.
"""

import json
import os
import tempfile
import unittest

from agent.config import AgentConfig
from agent.context import WorkingMemory
from agent.core.intent import Intent, IntentRouter
from agent.discovery import RepositoryDiscovery
from agent.intelligence import RepositoryScanner
from agent.pipeline.models import (
    StepStatus, PlanStep, IncrementalPlan,
    VerificationResult, ReviewResult, PipelineOutcome,
)
from agent.tools.safety import ToolSafetyGuard, SecurityError
from agent.tools import ToolRegistry
from agent.utils.logger import AgentLogger


class TestNEROCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        self.config = AgentConfig(repo_path=self.repo_path)
        self.memory = WorkingMemory(repo_path=self.repo_path)

        # Create dummy app structure
        os.makedirs(os.path.join(self.repo_path, "src"), exist_ok=True)
        with open(os.path.join(self.repo_path, "package.json"), "w") as f:
            f.write('{"name": "test-app", "dependencies": {"express": "^4.18.2", "mongoose": "^7.0.0"}}')
        with open(os.path.join(self.repo_path, "src", "app.js"), "w") as f:
            f.write('console.log("hello world");')
        with open(os.path.join(self.repo_path, "src", "Note.model.js"), "w") as f:
            f.write('const mongoose = require("mongoose");')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_safety_guard_path_traversal(self):
        safety = ToolSafetyGuard(self.config)
        valid = safety.resolve_and_validate_path(self.repo_path, "src/app.js")
        self.assertTrue(valid.startswith(self.repo_path.replace("\\", "/")))

        with self.assertRaises(SecurityError):
            safety.resolve_and_validate_path(self.repo_path, "../../etc/passwd")

    def test_repository_context_discovery(self):
        discovery = RepositoryDiscovery(self.config)
        ctx = discovery.discover(self.repo_path)

        self.assertEqual(ctx.primary_language, "JavaScript")
        self.assertIn("Express.js", ctx.detected_frameworks)
        self.assertIn("Mongoose / MongoDB", ctx.databases_and_orms)
        self.assertIn("src/app.js", ctx.entrypoints)
        self.assertIn("src/Note.model.js", ctx.models)
        self.assertEqual(ctx.architecture_map.primary_framework, "Express.js")

    def test_working_memory_caching_and_edits(self):
        self.memory.cache_file("src/app.js", "console.log('cached');")
        cached = self.memory.get_cached_file("src/app.js")
        self.assertEqual(cached, "console.log('cached');")

        self.memory.record_edit("src/app.js", "old content", "2026-07-27T12:00:00")
        self.assertIn("src/app.js", self.memory.get_edits_summary())

    def test_working_memory_cache_invalidated_after_edit(self):
        """Bug 4 fix: writing a file must evict it from the read cache."""
        self.memory.cache_file("src/app.js", "old content")
        self.assertIsNotNone(self.memory.get_cached_file("src/app.js"))

        # record_edit should evict the cache entry
        self.memory.record_edit("src/app.js", "old content", "2026-07-27T12:00:00")
        self.assertIsNone(self.memory.get_cached_file("src/app.js"),
                          "Cache entry should be evicted after an edit")

    def test_tool_registry_with_memory(self):
        registry = ToolRegistry(self.config, self.repo_path, memory=self.memory)

        # Test read_file caching
        res = registry.dispatch("read_file", {"path": "src/app.js"})
        self.assertIn("console.log", res)
        self.assertEqual(self.memory.get_cached_file("src/app.js"), 'console.log("hello world");')

        # Test targeted replace_text
        res_replace = registry.dispatch("replace_text", {
            "path": "src/app.js",
            "old_text": 'console.log("hello world");',
            "new_text": 'console.log("hello NERO");',
        })
        self.assertIn("Successfully replaced", res_replace)
        # Test clone_repo tool dispatch
        res_clone = registry.dispatch("clone_repo", {"url_or_path": self.repo_path})
        self.assertIn("Successfully cloned/loaded", res_clone)


class TestIntentRouter(unittest.TestCase):
    """Tests for the IntentRouter — LLM-free classification engine."""

    def setUp(self):
        self.router = IntentRouter()

    def test_status_exact(self):
        self.assertEqual(self.router.classify("status"), Intent.STATUS)
        self.assertEqual(self.router.classify("/status"), Intent.STATUS)
        self.assertEqual(self.router.classify("working memory"), Intent.STATUS)

    def test_diff_exact(self):
        self.assertEqual(self.router.classify("/diff"), Intent.DIFF)
        self.assertEqual(self.router.classify("show diff"), Intent.DIFF)
        self.assertEqual(self.router.classify("what changed"), Intent.DIFF)

    def test_undo_exact(self):
        self.assertEqual(self.router.classify("/undo"), Intent.UNDO)
        self.assertEqual(self.router.classify("revert"), Intent.UNDO)

    def test_context_exact(self):
        self.assertEqual(self.router.classify("/context"), Intent.CONTEXT)
        self.assertEqual(self.router.classify("show context"), Intent.CONTEXT)

    def test_routes_exact(self):
        self.assertEqual(self.router.classify("/routes"), Intent.ROUTES)
        self.assertEqual(self.router.classify("list api endpoints"), Intent.ROUTES)

    def test_repository_clone_url(self):
        self.assertEqual(
            self.router.classify("clone https://github.com/user/repo.git"),
            Intent.REPOSITORY,
        )

    def test_repository_switch(self):
        self.assertEqual(
            self.router.classify("switch to the repo at ./my_app"),
            Intent.REPOSITORY,
        )

    def test_verify_run_tests(self):
        self.assertEqual(self.router.classify("run the tests"), Intent.VERIFY)
        self.assertEqual(self.router.classify("run unit tests"), Intent.VERIFY)
        self.assertEqual(self.router.classify("npm test"), Intent.VERIFY)
        self.assertEqual(self.router.classify("pytest"), Intent.VERIFY)

    def test_review_changes(self):
        self.assertEqual(self.router.classify("review my changes"), Intent.REVIEW)
        self.assertEqual(self.router.classify("code review"), Intent.REVIEW)

    def test_symbols_where_defined(self):
        self.assertEqual(
            self.router.classify("where is createNote defined?"),
            Intent.SYMBOLS,
        )
        self.assertEqual(
            self.router.classify("find the definition of getAllNotes"),
            Intent.SYMBOLS,
        )

    def test_search_find_all(self):
        self.assertEqual(
            self.router.classify("find all uses of mongoose in the codebase"),
            Intent.SEARCH,
        )
        self.assertEqual(
            self.router.classify("where is mongoose imported?"),
            Intent.SEARCH,
        )

    def test_explain_how(self):
        self.assertEqual(
            self.router.classify("explain how the note creation works"),
            Intent.EXPLAIN,
        )
        self.assertEqual(
            self.router.classify("how does the authentication middleware work?"),
            Intent.EXPLAIN,
        )

    def test_modify_add_feature(self):
        self.assertEqual(
            self.router.classify("add a tags field to the Note model"),
            Intent.MODIFY,
        )
        self.assertEqual(
            self.router.classify("implement pagination for the notes endpoint"),
            Intent.MODIFY,
        )
        self.assertEqual(
            self.router.classify("fix the bug where notes are not sorted by date"),
            Intent.MODIFY,
        )
        self.assertEqual(
            self.router.classify("refactor the controller to use async/await"),
            Intent.MODIFY,
        )
        self.assertEqual(
            self.router.classify("create a new route for searching notes"),
            Intent.MODIFY,
        )
        self.assertEqual(
            self.router.classify("Improve the application so users can better organise and search their notes."),
            Intent.MODIFY,
        )

    def test_modify_imperative(self):
        self.assertEqual(self.router.classify("add logging to the app"), Intent.MODIFY)
        self.assertEqual(self.router.classify("update the README"), Intent.MODIFY)
        self.assertEqual(self.router.classify("improve performance of notes database"), Intent.MODIFY)

    def test_conversation_default(self):
        self.assertEqual(
            self.router.classify("what's the best database for this project?"),
            Intent.CONVERSATION,
        )

    def test_search_gets_one_tool(self):
        tools = self.router.get_tool_names(Intent.SEARCH)
        self.assertEqual(tools, ["search_code_content"])

    def test_modify_gets_all_tools(self):
        tools = self.router.get_tool_names(Intent.MODIFY)
        self.assertIsNone(tools, "MODIFY should receive None = all tools")

    def test_inline_intents_get_empty_tools(self):
        for intent in (Intent.STATUS, Intent.DIFF, Intent.UNDO,
                       Intent.CONTEXT, Intent.ROUTES):
            tools = self.router.get_tool_names(intent)
            self.assertEqual(tools, [], f"{intent} should have no tools (inline handler)")
            self.assertTrue(self.router.is_inline(intent))

    def test_explain_gets_limited_tools(self):
        tools = self.router.get_tool_names(Intent.EXPLAIN)
        self.assertIsNotNone(tools)
        self.assertIn("read_file", tools)
        self.assertIn("search_code_content", tools)
        self.assertNotIn("write_file", tools)
        self.assertNotIn("run_command", tools)

    def test_verify_gets_limited_tools(self):
        tools = self.router.get_tool_names(Intent.VERIFY)
        self.assertIsNotNone(tools)
        self.assertIn("run_command", tools)
        self.assertNotIn("write_file", tools)

    def test_scanner_detects_js_project(self):
        """RepositoryScanner must correctly analyse a minimal JS repo."""
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentConfig(repo_path=tmp)
            with open(os.path.join(tmp, "package.json"), "w") as f:
                f.write('{"dependencies": {"express": "4.x", "mongoose": "7.x"}}')
            with open(os.path.join(tmp, "server.js"), "w") as f:
                f.write("const express = require('express');\nconst app = express();\n")

            scanner = RepositoryScanner(config)
            ctx = scanner.scan(tmp)

            self.assertEqual(ctx.primary_language, "JavaScript")
            self.assertIn("Express.js", ctx.detected_frameworks)
            self.assertIn("Mongoose / MongoDB", ctx.databases_and_orms)
            self.assertIn("server.js", ctx.entrypoints)
            self.assertGreater(ctx.total_files_count, 0)

    def test_scanner_framework_no_false_positive_from_comment(self):
        """
        Regression test for the requirements.txt false-positive bug.
        A comment mentioning 'django' must NOT trigger Django detection.
        """
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentConfig(repo_path=tmp)
            with open(os.path.join(tmp, "requirements.txt"), "w") as f:
                f.write("# We chose flask over django for simplicity\nflask>=2.0\n")
            with open(os.path.join(tmp, "app.py"), "w") as f:
                f.write("from flask import Flask\napp = Flask(__name__)\n")

            scanner = RepositoryScanner(config)
            ctx = scanner.scan(tmp)

            self.assertIn("Flask", ctx.detected_frameworks)
            self.assertNotIn("Django", ctx.detected_frameworks,
                             "Django mentioned only in a comment must NOT be detected")

    def test_symbol_index_python_extraction(self):
        """PythonExtractor must correctly index functions and classes."""
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentConfig(repo_path=tmp)
            with open(os.path.join(tmp, "models.py"), "w") as f:
                f.write(
                    "class Note:\n"
                    "    '''A note model.'''\n"
                    "    def save(self):\n"
                    "        pass\n"
                    "\n"
                    "def create_note(title, content):\n"
                    "    '''Create a new note.'''\n"
                    "    return Note()\n"
                )

            scanner = RepositoryScanner(config)
            ctx = scanner.scan(tmp)

            names = [s.name for s in ctx.symbols]
            self.assertIn("Note", names)
            self.assertIn("create_note", names)


class TestPipeline(unittest.TestCase):
    """Tests for Phase 4 pipeline data structures and components."""

    def test_plan_step_lifecycle(self):
        step = PlanStep(id=1, description="Add tags field")
        self.assertEqual(step.status, StepStatus.PENDING)
        self.assertFalse(step.is_terminal)

        step.mark_in_progress()
        self.assertEqual(step.status, StepStatus.IN_PROGRESS)
        self.assertFalse(step.is_terminal)

        step.mark_done("Done.")
        self.assertEqual(step.status, StepStatus.COMPLETED)
        self.assertTrue(step.is_terminal)

    def test_plan_step_failure(self):
        step = PlanStep(id=2, description="Run migration")
        step.mark_failed("File not found")
        self.assertEqual(step.status, StepStatus.FAILED)
        self.assertEqual(step.error, "File not found")
        self.assertTrue(step.is_terminal)

    def test_incremental_plan_progress(self):
        steps = [
            PlanStep(id=1, description="Step 1"),
            PlanStep(id=2, description="Step 2"),
            PlanStep(id=3, description="Step 3"),
        ]
        plan = IncrementalPlan(
            goal="Add tags",
            understanding="",
            approach="",
            affected_files=["models.py"],
            steps=steps,
            validation_commands=["pytest"],
            risks=[],
            created_at="2026-07-27T00:00:00",
        )
        self.assertEqual(len(plan.pending_steps()), 3)
        self.assertFalse(plan.is_complete())

        steps[0].mark_done()
        steps[1].mark_done()
        self.assertEqual(len(plan.completed_steps()), 2)

        steps[2].mark_failed("Error")
        self.assertTrue(plan.is_complete())
        self.assertEqual(len(plan.failed_steps()), 1)

    def test_plan_format_for_display_contains_goal(self):
        plan = IncrementalPlan(
            goal="Add tags field to Note",
            understanding="",
            approach="Simple field addition",
            affected_files=["models/note.py"],
            steps=[PlanStep(id=1, description="Edit Note model")],
            validation_commands=["pytest"],
            risks=["May require migration"],
            created_at="2026-07-27T00:00:00",
        )
        display = plan.format_for_display()
        self.assertIn("Add tags field to Note", display)
        self.assertIn("Edit Note model", display)
        self.assertIn("pytest", display)
        self.assertIn("May require migration", display)

    def test_verification_result_passed(self):
        result = VerificationResult(
            passed=True,
            command="pytest",
            exit_code=0,
            stdout="5 passed",
            stderr="",
        )
        self.assertTrue(result.passed)
        llm_fmt = result.format_for_llm()
        self.assertIn("PASSED", llm_fmt)
        self.assertIn("pytest", llm_fmt)

    def test_verification_result_failed_with_tests(self):
        result = VerificationResult(
            passed=False,
            command="pytest",
            exit_code=1,
            stdout="FAILED tests/test_note.py::test_tags",
            stderr="",
            failed_tests=["tests/test_note.py::test_tags"],
            error_summary="AssertionError: expected tags field",
        )
        self.assertFalse(result.passed)
        llm_fmt = result.format_for_llm()
        self.assertIn("FAILED", llm_fmt)
        self.assertIn("test_tags", llm_fmt)

    def test_review_result_approved(self):
        result = ReviewResult(
            approved=True,
            summary="Changes correctly implement the tags feature.",
            concerns=[],
            suggestions=["Consider adding an index on the tags column."],
        )
        display = result.format_for_display()
        self.assertIn("APPROVED", display)
        self.assertIn("tags column", display)

    def test_review_result_rejected(self):
        result = ReviewResult(
            approved=False,
            summary="Tags field not persisted correctly.",
            concerns=["Missing migration file."],
            suggestions=[],
        )
        display = result.format_for_display()
        self.assertIn("NEEDS WORK", display)
        self.assertIn("migration", display)

    def test_pipeline_outcome_success_summary(self):
        plan = IncrementalPlan(
            goal="Add tags",
            understanding="",
            approach="",
            affected_files=["models.py", "migrations/001.py"],
            steps=[
                PlanStep(id=1, description="Edit model", status=StepStatus.COMPLETED),
                PlanStep(id=2, description="Add migration", status=StepStatus.COMPLETED),
            ],
            validation_commands=["pytest"],
            risks=[],
            created_at="2026-07-27T00:00:00",
        )
        verification = VerificationResult(
            passed=True, command="pytest", exit_code=0, stdout="2 passed", stderr=""
        )
        review = ReviewResult(approved=True, summary="Looks good.")
        outcome = PipelineOutcome(
            success=True,
            plan=plan,
            verification=verification,
            review=review,
            repair_attempts=0,
        )
        summary = outcome.format_session_summary()
        self.assertIn("Completed", summary)
        self.assertIn("Add tags", summary)
        self.assertIn("models.py", summary)
        self.assertIn("passed", summary)

    def test_pipeline_outcome_aborted_summary(self):
        plan = IncrementalPlan(
            goal="Add tags",
            understanding="", approach="", affected_files=[],
            steps=[PlanStep(id=1, description="(aborted)", status=StepStatus.PENDING)],
            validation_commands=[], risks=[], created_at="2026-07-27T00:00:00",
        )
        outcome = PipelineOutcome(
            success=False,
            plan=plan,
            abort_reason="User cancelled: User declined to proceed.",
        )
        summary = outcome.format_session_summary()
        self.assertIn("Incomplete", summary)
        self.assertIn("User cancelled", summary)

    def test_planner_parses_valid_json(self):
        """Planner must parse valid JSON plan into typed IncrementalPlan."""
        from agent.pipeline.planner import IncrementalPlanner
        planner = IncrementalPlanner(router=None)

        raw_json = json.dumps({
            "goal": "Add tags field to Note model",
            "understanding": "Need to add a tags array field",
            "approach": "Edit the Mongoose schema",
            "affected_files": ["src/models/Note.js"],
            "steps": [
                {"id": 1, "description": "Add tags field", "target_files": ["src/models/Note.js"]},
                {"id": 2, "description": "Update controller", "target_files": ["src/controllers/note.js"]},
            ],
            "validation_commands": ["npm test"],
            "risks": ["May require data migration"],
        })
        plan = planner._parse_plan(raw_json, model_used="test")

        self.assertEqual(plan.goal, "Add tags field to Note model")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].id, 1)
        self.assertEqual(plan.steps[0].description, "Add tags field")
        self.assertEqual(plan.steps[0].target_files, ["src/models/Note.js"])
        self.assertEqual(plan.validation_commands, ["npm test"])
        self.assertEqual(plan.risks, ["May require data migration"])
        self.assertEqual(plan.model_used, "test")

    def test_planner_parses_json_in_markdown_fence(self):
        """Planner must strip markdown code fences before parsing."""
        from agent.pipeline.planner import IncrementalPlanner
        planner = IncrementalPlanner(router=None)

        raw = '```json\n{"goal": "Fix bug", "steps": [{"id": 1, "description": "Fix it"}]}\n```'
        plan = planner._parse_plan(raw)
        self.assertEqual(plan.goal, "Fix bug")
        self.assertEqual(len(plan.steps), 1)

    def test_planner_raises_on_missing_goal(self):
        """Planner must raise PlannerError if 'goal' is missing."""
        from agent.pipeline.planner import IncrementalPlanner, PlannerError
        planner = IncrementalPlanner(router=None)

        raw = json.dumps({"steps": [{"id": 1, "description": "Do something"}]})
        with self.assertRaises(PlannerError):
            planner._parse_plan(raw)

    def test_planner_caps_steps_at_12(self):
        """Planner must not produce more than 12 steps."""
        from agent.pipeline.planner import IncrementalPlanner
        planner = IncrementalPlanner(router=None)

        steps = [{"id": i, "description": f"Step {i}"} for i in range(1, 20)]
        raw = json.dumps({"goal": "Big task", "steps": steps})
        plan = planner._parse_plan(raw)
        self.assertLessEqual(len(plan.steps), 12)

    def test_planner_raises_on_no_json(self):
        """Planner must raise PlannerError if response has no JSON object."""
        from agent.pipeline.planner import IncrementalPlanner, PlannerError
        planner = IncrementalPlanner(router=None)

        with self.assertRaises(PlannerError):
            planner._parse_plan("Sorry, I cannot help with that.")

    def test_verifier_auto_detects_pytest(self):
        """VerificationEngine must auto-detect pytest for Python projects."""
        from agent.pipeline.verifier import VerificationEngine
        config = AgentConfig()
        logger = AgentLogger(verbose=False)
        engine = VerificationEngine(config, logger)

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "pytest.ini"), "w") as f:
                f.write("[pytest]\n")
            commands = engine._auto_detect_commands(tmp)
            self.assertEqual(commands, ["pytest"])

    def test_verifier_auto_detects_npm(self):
        """VerificationEngine must auto-detect npm test for Node projects."""
        from agent.pipeline.verifier import VerificationEngine
        config = AgentConfig()
        logger = AgentLogger(verbose=False)
        engine = VerificationEngine(config, logger)

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w") as f:
                f.write('{"scripts": {"test": "jest"}}')
            commands = engine._auto_detect_commands(tmp)
            self.assertEqual(commands, ["npm test"])

    def test_verifier_rejects_disallowed_command(self):
        """VerificationEngine must reject commands not in the allow-list."""
        from agent.pipeline.verifier import VerificationEngine
        config = AgentConfig()
        logger = AgentLogger(verbose=False)
        engine = VerificationEngine(config, logger)

        with tempfile.TemporaryDirectory() as tmp:
            result = engine._run_one("rm -rf /", tmp)
            self.assertFalse(result.passed)
            self.assertIn("not in allow-list", result.stderr)

    def test_verifier_extracts_pytest_failures(self):
        """VerificationEngine must extract FAILED test names from output."""
        from agent.pipeline.verifier import VerificationEngine
        output = (
            "FAILED tests/test_note.py::test_create_note\n"
            "FAILED tests/test_note.py::test_delete_note\n"
            "2 failed, 5 passed\n"
        )
        failed = VerificationEngine._extract_failed_tests(output)
        self.assertIn("tests/test_note.py::test_create_note", failed)
        self.assertIn("tests/test_note.py::test_delete_note", failed)


class TestPhase5(unittest.TestCase):
    """Tests for Phase 5 Developer Experience commands (/architecture, /resume)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        self.config = AgentConfig(repo_path=self.repo_path)
        self.memory = WorkingMemory(repo_path=self.repo_path)
        
        class MockLogger:
            def __init__(self):
                self.messages = []
            def markdown(self, text):
                self.messages.append(text)
            def progress(self, text):
                self.messages.append(text)
            def warning(self, text):
                self.messages.append(text)
            def success(self, text):
                self.messages.append(text)
            def error(self, text):
                self.messages.append(text)

        self.logger = MockLogger()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_intent_router_new_commands(self):
        router = IntentRouter()
        self.assertEqual(router.classify("/architecture"), Intent.ARCHITECTURE)
        self.assertEqual(router.classify("architecture overview"), Intent.ARCHITECTURE)
        self.assertEqual(router.classify("/resume"), Intent.RESUME)
        self.assertEqual(router.classify("continue the plan"), Intent.RESUME)

    def test_handle_architecture_query_no_context(self):
        from agent.agent_core import AgentCore
        agent = AgentCore(self.config, self.memory, logger=self.logger)
        agent._handle_architecture_query()
        self.assertTrue(any("Repository not yet analyzed" in msg for msg in self.logger.messages))

    def test_handle_architecture_query_with_context(self):
        from agent.agent_core import AgentCore
        from agent.intelligence.context import RepositoryContext, ArchitectureMap
        agent = AgentCore(self.config, self.memory, logger=self.logger)
        
        ctx = RepositoryContext(
            repo_path=self.repo_path,
            primary_language="Python",
            detected_frameworks=["FastAPI"],
            databases_and_orms=["SQLAlchemy"],
            architecture_map=ArchitectureMap(
                pattern="REST API Layered",
                primary_framework="FastAPI",
                component_graph={"routers": ["routes/notes.py"]}
            ),
            entrypoints=["main.py"],
            models=["models.py"],
            env_variables=["DATABASE_URL"],
            total_files_count=10
        )
        self.memory.repo_context = ctx
        
        agent._handle_architecture_query()
        output = "\n".join(self.logger.messages)
        self.assertIn("Repository Architecture", output)
        self.assertIn("REST API Layered", output)
        self.assertIn("FastAPI", output)
        self.assertIn("SQLAlchemy", output)
        self.assertIn("DATABASE_URL", output)

    def test_handle_resume_no_plan(self):
        from agent.agent_core import AgentCore
        agent = AgentCore(self.config, self.memory, logger=self.logger)
        agent._handle_resume()
        self.assertTrue(any("No active plan to resume" in msg for msg in self.logger.messages))

    def test_handle_resume_all_steps_completed(self):
        from agent.agent_core import AgentCore
        from agent.pipeline.models import IncrementalPlan, PlanStep, StepStatus
        agent = AgentCore(self.config, self.memory, logger=self.logger)
        
        plan = IncrementalPlan(
            goal="Add tags",
            understanding="",
            approach="",
            affected_files=[],
            steps=[PlanStep(id=1, description="Step 1", status=StepStatus.COMPLETED)],
            validation_commands=[],
            risks=[],
            created_at="2026-07-27"
        )
        self.memory.current_plan = plan
        
        agent._handle_resume()
        output = "\n".join(self.logger.messages)
        self.assertIn("already complete", output)

    def test_handle_resume_runs_executor(self):
        from agent.agent_core import AgentCore
        from agent.pipeline.models import IncrementalPlan, PlanStep, StepStatus
        from unittest.mock import MagicMock
        agent = AgentCore(self.config, self.memory, logger=self.logger)
        
        plan = IncrementalPlan(
            goal="Add tags",
            understanding="",
            approach="",
            affected_files=[],
            steps=[PlanStep(id=1, description="Step 1", status=StepStatus.PENDING)],
            validation_commands=[],
            risks=[],
            created_at="2026-07-27"
        )
        self.memory.current_plan = plan
        
        from agent.intelligence.context import RepositoryContext
        ctx = RepositoryContext(repo_path=self.repo_path)
        self.memory.repo_context = ctx
        
        agent._get_orchestrator = MagicMock()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = (plan, "DONE:")
        agent._get_orchestrator.return_value._executor = mock_executor
        
        agent._handle_resume()
        mock_executor.execute.assert_called_once()
        self.assertTrue(any("Resuming plan" in msg for msg in self.logger.messages))

    def test_intent_router_bare_clone(self):
        router = IntentRouter()
        self.assertEqual(router.classify("clone the repo"), Intent.REPOSITORY)
        self.assertEqual(router.classify("git clone"), Intent.REPOSITORY)

    def test_process_prompt_no_workspace_error_handled(self):
        from agent.agent_core import AgentCore
        non_existent_path = os.path.join(self.repo_path, "does_not_exist")
        self.config.repo_path = non_existent_path
        agent = AgentCore(self.config, self.memory, logger=self.logger)

        agent.process_prompt("add tags field to Note model")
        output = "\n".join(self.logger.messages)
        self.assertIn("No workspace found", output)
        self.assertIn("Clone a repo", output)

    def test_process_prompt_no_workspace_conversation(self):
        from agent.agent_core import AgentCore
        from unittest.mock import MagicMock
        non_existent_path = os.path.join(self.repo_path, "does_not_exist")
        self.config.repo_path = non_existent_path
        agent = AgentCore(self.config, self.memory, logger=self.logger)

        mock_chat = MagicMock()
        from agent.llm.base import LLMResponse
        mock_chat.return_value = LLMResponse(content="Hello there!", tool_calls=[])
        agent.router.chat = mock_chat

        agent.process_prompt("hi")
        mock_chat.assert_called_once()
        self.assertTrue(any("Hello there!" in msg for msg in self.logger.messages))

    def test_process_prompt_no_workspace_clone_loop(self):
        from agent.agent_core import AgentCore
        from unittest.mock import MagicMock
        non_existent_path = os.path.join(self.repo_path, "does_not_exist")
        self.config.repo_path = non_existent_path
        agent = AgentCore(self.config, self.memory, logger=self.logger)

        mock_chat = MagicMock()
        from agent.llm.base import LLMResponse
        mock_chat.return_value = LLMResponse(content="Ask for URL or run clone", tool_calls=[])
        agent.router.chat = mock_chat

        agent.process_prompt("clone the repo")
        mock_chat.assert_called_once()
        self.assertTrue(any("Ask for URL or run clone" in msg for msg in self.logger.messages))


if __name__ == "__main__":
    unittest.main()
