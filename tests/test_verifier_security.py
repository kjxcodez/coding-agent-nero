"""
Unit tests for P1.5 fix: removing shell=True and adding strict shell character rejection.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.config import AgentConfig
from agent.pipeline.verifier import VerificationEngine


class TestVerifierSecurity(unittest.TestCase):
    def setUp(self):
        self.config = AgentConfig()
        # Ensure standard prefixes are set
        self.config.allowed_command_prefixes = (
            "npm test",
            "pytest",
            "python -m pytest",
            "cargo test",
        )
        self.logger = MagicMock()
        self.engine = VerificationEngine(self.config, self.logger)

    def test_legitimate_commands_are_allowed(self):
        """Standard allowed commands must pass the _is_allowed check."""
        self.assertTrue(self.engine._is_allowed("npm test"))
        self.assertTrue(self.engine._is_allowed("pytest"))
        self.assertTrue(self.engine._is_allowed("python -m pytest"))
        self.assertTrue(self.engine._is_allowed("cargo test"))
        self.assertTrue(self.engine._is_allowed("pytest -v --tb=short"))

    def test_disallowed_prefix_is_rejected(self):
        """Commands that do not match the allow-list prefix must be rejected."""
        self.assertFalse(self.engine._is_allowed("rm -rf /"))
        self.assertFalse(self.engine._is_allowed("echo hello"))

    def test_command_chaining_is_rejected(self):
        """Commands containing chaining operators like &&, ;, | must be rejected."""
        self.assertFalse(self.engine._is_allowed("npm test && echo hacked"))
        self.assertFalse(self.engine._is_allowed("pytest; rm -rf /"))
        self.assertFalse(self.engine._is_allowed("pytest | cat"))
        self.assertFalse(self.engine._is_allowed("pytest & echo hacked"))

    def test_redirection_is_rejected(self):
        """Commands containing redirection operators like >, < must be rejected."""
        self.assertFalse(self.engine._is_allowed("pytest > output.txt"))
        self.assertFalse(self.engine._is_allowed("pytest < input.txt"))

    def test_command_substitution_is_rejected(self):
        """Commands containing $ or ` for command substitution must be rejected."""
        self.assertFalse(self.engine._is_allowed("pytest $(whoami)"))
        self.assertFalse(self.engine._is_allowed("pytest `whoami`"))

    def test_environment_expansion_is_rejected(self):
        """Commands containing % or ! (Windows expansion chars) must be rejected."""
        self.assertFalse(self.engine._is_allowed("pytest %USERPROFILE%"))
        self.assertFalse(self.engine._is_allowed("pytest !VAR!"))

    def test_run_one_disallowed_command(self):
        """_run_one must return a failed VerificationResult without calling subprocess for disallowed commands."""
        with patch("subprocess.run") as mock_run:
            res = self.engine._run_one("pytest && echo vulnerable", "/fake/cwd")
            self.assertFalse(res.passed)
            self.assertIn("not in allow-list", res.stderr)
            mock_run.assert_not_called()

    def test_run_one_mismatched_quotes_handled_gracefully(self):
        """Mismatched quotes in command string must return a failed VerificationResult gracefully."""
        res = self.engine._run_one('pytest "unclosed quote', "/fake/cwd")
        self.assertFalse(res.passed)
        self.assertIn("Failed to parse command arguments", res.stderr)

    @patch("subprocess.run")
    def test_subprocess_run_called_with_list_and_shell_false(self, mock_run):
        """subprocess.run must be called with an argument list and shell=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "all tests passed"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = self.engine._run_one("pytest -v", "/fake/cwd")

        self.assertTrue(res.passed)
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        # First argument should be resolved or stay pytest
        self.assertTrue(called_args[0].endswith("pytest") or called_args[0] == "pytest")
        self.assertEqual(called_args[1], "-v")
        self.assertFalse(mock_run.call_args[1].get("shell", True))


if __name__ == "__main__":
    unittest.main()
