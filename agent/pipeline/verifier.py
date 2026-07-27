"""
VerificationEngine — Phase 4, Step 3 of the MODIFY pipeline.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from ..config import AgentConfig
from ..utils.logger import AgentLogger
from .models import VerificationResult


class VerificationEngine:
    """Runs test/lint/build commands and returns a typed VerificationResult."""

    def __init__(self, config: AgentConfig, logger: AgentLogger) -> None:
        self._config = config
        self._logger = logger

    def verify(
        self,
        repo_path: str,
        commands: Optional[List[str]] = None,
    ) -> VerificationResult:
        if not commands:
            commands = self._auto_detect_commands(repo_path)

        if not commands:
            self._logger.warning(
                "VerificationEngine: No validation commands found. "
                "Verification skipped."
            )
            return VerificationResult(
                passed=True,
                command="(none)",
                exit_code=0,
                stdout="No validation commands configured or detected.",
                stderr="",
                error_summary="Skipped — no commands.",
            )

        result = VerificationResult(passed=True, command="", exit_code=0, stdout="", stderr="")
        for cmd in commands:
            result = self._run_one(cmd, repo_path)
            if not result.passed:
                return result

        return result

    def _run_one(self, command: str, cwd: str) -> VerificationResult:
        if not self._is_allowed(command):
            msg = (
                f"Command not in allow-list: `{command}`. "
                f"Allowed prefixes: {list(self._config.allowed_command_prefixes)}"
            )
            self._logger.warning(f"VerificationEngine: {msg}")
            return VerificationResult(
                passed=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=msg,
                error_summary=msg,
            )

        self._logger.progress(f"Verifying: {command}")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=120,
            )
            passed = proc.returncode == 0
            failed_tests = self._extract_failed_tests(proc.stdout + proc.stderr)
            error_summary = self._summarise_failure(
                proc.stdout, proc.stderr, proc.returncode
            ) if not passed else ""

            return VerificationResult(
                passed=passed,
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout[-4000:],
                stderr=proc.stderr[-2000:],
                failed_tests=failed_tests,
                error_summary=error_summary,
            )
        except subprocess.TimeoutExpired:
            msg = f"Command timed out after 120s: `{command}`"
            self._logger.error(msg)
            return VerificationResult(
                passed=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=msg,
                error_summary=msg,
            )
        except Exception as exc:
            msg = f"Command failed with exception: {exc}"
            self._logger.error(msg)
            return VerificationResult(
                passed=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                error_summary=msg,
            )

    def _is_allowed(self, command: str) -> bool:
        cmd = command.strip()
        # Verify if command starts with an allowed prefix
        for prefix in self._config.allowed_command_prefixes:
            if cmd == prefix or cmd.startswith(prefix + " "):
                return True
        return False

    def _auto_detect_commands(self, repo_path: str) -> List[str]:
        files = set(os.listdir(repo_path)) if os.path.isdir(repo_path) else set()

        if any(f in files for f in ("pytest.ini", "setup.py", "pyproject.toml", "setup.cfg")):
            return ["pytest"]
        if "requirements.txt" in files:
            return ["python -m pytest"]
        if "package.json" in files:
            return ["npm test"]
        if "Cargo.toml" in files:
            return ["cargo test"]

        return []

    @staticmethod
    def _extract_failed_tests(output: str) -> List[str]:
        import re
        failed: List[str] = []
        for m in re.finditer(r"FAILED\s+([\w/\\:\.]+)", output):
            failed.append(m.group(1))
        for m in re.finditer(r"^\s+[●×✕]\s+(.+)$", output, re.M):
            failed.append(m.group(1).strip())
        return failed[:20]

    @staticmethod
    def _summarise_failure(stdout: str, stderr: str, exit_code: int) -> str:
        combined = (stderr + "\n" + stdout).strip()
        lines = combined.splitlines()
        error_lines = [
            l for l in lines
            if any(kw in l.lower() for kw in (
                "error", "fail", "exception", "assert", "traceback", "fatal"
            ))
        ]
        relevant = error_lines[:15] or lines[-15:]
        return "\n".join(relevant)
