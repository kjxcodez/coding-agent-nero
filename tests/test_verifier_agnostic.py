"""
Comprehensive unit tests for the language-agnostic verification fallback system (P2.1).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agent.config import AgentConfig
from agent.pipeline.models import VerificationResult
from agent.pipeline.verifier import VerificationEngine


class TestVerifierAgnostic(unittest.TestCase):
    def setUp(self):
        self.config = AgentConfig()
        self.logger = MagicMock()
        self.engine = VerificationEngine(self.config, self.logger)

    def test_detect_ecosystem_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w") as f:
                f.write("{}")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "node")

    def test_detect_ecosystem_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "requirements.txt"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "python")

    def test_detect_ecosystem_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "go.mod"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "go")

    def test_detect_ecosystem_rust(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "Cargo.toml"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "rust")

    def test_detect_ecosystem_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "pom.xml"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "java")

    def test_detect_ecosystem_dotnet(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "App.sln"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "dotnet")

    def test_detect_ecosystem_php(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "composer.json"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "php")

    def test_detect_ecosystem_ruby(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "Gemfile"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._detect_ecosystem(tmp), "ruby")

    def test_detect_ecosystem_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.engine._detect_ecosystem(tmp), "generic")

    def test_auto_detect_commands_priority(self):
        """Verifier must correctly identify package manager by lockfiles."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmp, "pnpm-lock.yaml"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._auto_detect_commands(tmp), ["pnpm test"])

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmp, "yarn.lock"), "w") as f:
                f.write("")
            self.assertEqual(self.engine._auto_detect_commands(tmp), ["yarn test"])

    @patch("agent.pipeline.verifier.subprocess.run")
    def test_python_fallback_execution(self, mock_run):
        """Python fallback compiles Python files using compileall."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Compiled"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        with tempfile.TemporaryDirectory() as tmp:
            res = self.engine._run_python_fallback(tmp)
            self.assertTrue(res.passed)
            self.assertEqual(res.command, "python compileall")
            mock_run.assert_called_once()
            called_args = mock_run.call_args[0][0]
            self.assertTrue(called_args[0].lower().endswith("python") or called_args[0].lower().endswith("python.exe"))
            self.assertEqual(called_args[1:3], ["-m", "compileall"])

    @patch("agent.pipeline.verifier.subprocess.run")
    def test_go_fallback_execution(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        with tempfile.TemporaryDirectory() as tmp:
            res = self.engine._run_go_fallback(tmp)
            self.assertTrue(res.passed)
            mock_run.assert_called_once()
            called_args = mock_run.call_args[0][0]
            self.assertTrue(called_args[0].lower().endswith("go") or called_args[0].lower().endswith("go.exe"))
            self.assertEqual(called_args[1], "build")

    @patch("agent.pipeline.verifier.subprocess.run")
    def test_rust_fallback_execution(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        with tempfile.TemporaryDirectory() as tmp:
            res = self.engine._run_rust_fallback(tmp)
            self.assertTrue(res.passed)
            called_args = mock_run.call_args[0][0]
            self.assertTrue(called_args[0].lower().endswith("cargo") or called_args[0].lower().endswith("cargo.exe"))
            self.assertEqual(called_args[1], "build")

    def test_generic_fallback_graceful_skip(self):
        """Generic repositories must skip validation gracefully rather than failing."""
        res = self.engine._run_fallback_verification("/fake/path", "generic")
        self.assertTrue(res.passed)
        self.assertEqual(res.classification, "Verification Succeeded")
        self.assertIn("generic", res.command)

    def test_is_missing_test_error_classification(self):
        # pytest missing tests
        res = VerificationResult(
            passed=False, command="pytest", exit_code=1, stdout="collected 0 items / 1 error", stderr=""
        )
        self.assertTrue(self.engine._is_missing_test_error(res))

        # actual test failure
        res2 = VerificationResult(
            passed=False, command="pytest", exit_code=1, stdout="FAILED tests/test_foo.py::test_bar", stderr=""
        )
        self.assertFalse(self.engine._is_missing_test_error(res2))

    def test_classify_failure_syntax_error(self):
        res = VerificationResult(
            passed=False, command="pytest", exit_code=1, stdout="SyntaxError: invalid syntax", stderr=""
        )
        self.assertEqual(self.engine._classify_failure(res), "Syntax Error")

    def test_classify_failure_missing_dependency(self):
        res = VerificationResult(
            passed=False, command="node index.js", exit_code=1, stdout="Error: Cannot find module 'express'", stderr=""
        )
        self.assertEqual(self.engine._classify_failure(res), "Missing Dependency")

    def test_classify_failure_missing_database(self):
        res = VerificationResult(
            passed=False,
            command="pytest",
            exit_code=1,
            stdout="sqlite3.OperationalError: no such table: notes",
            stderr="",
        )
        self.assertEqual(self.engine._classify_failure(res), "Missing Database")

        res2 = VerificationResult(
            passed=False,
            command="node server.js",
            exit_code=1,
            stdout="MongooseServerSelectionError: connect ECONNREFUSED 127.0.0.1:27017",
            stderr="",
        )
        self.assertEqual(self.engine._classify_failure(res2), "Missing Database")

    def test_populate_result_bypasses_missing_database(self):
        res = VerificationResult(
            passed=False,
            command="node server.js",
            exit_code=1,
            stdout="MongooseServerSelectionError: connect ECONNREFUSED 127.0.0.1:27017",
            stderr="",
        )
        populated = self.engine._populate_result(res)
        self.assertTrue(populated.passed)
        self.assertEqual(populated.classification, "Verification Succeeded (Missing Database Bypassed)")

    @patch("agent.pipeline.verifier.subprocess.run")
    @patch("agent.pipeline.verifier.subprocess.Popen")
    def test_node_boot_check_execution(self, mock_popen, mock_run):
        """Node boot check starts server.js and terminates it cleanly after 2s."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # means process is still running after 2s
        mock_popen.return_value = mock_proc

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "server.js"), "w") as f:
                f.write("// Server code")
            res = self.engine._run_node_boot_check(tmp)
            self.assertTrue(res.passed)
            mock_popen.assert_called_once()
            called_args = mock_popen.call_args[0][0]
            self.assertTrue(called_args[0].lower().endswith("node") or called_args[0].lower().endswith("node.exe"))
            self.assertEqual(called_args[1], "server.js")
            mock_proc.terminate.assert_called_once()

    def test_node_boot_check_skipped_when_no_entrypoint(self):
        """Boot check must not run if no entrypoint is found."""
        with tempfile.TemporaryDirectory() as tmp:
            res = self.engine._run_node_boot_check(tmp)
            self.assertTrue(res.passed)
            self.assertEqual(res.command, "node boot check")
            self.assertIn("skipped", res.stdout)


if __name__ == "__main__":
    unittest.main()
