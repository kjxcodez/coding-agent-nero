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

        # Intercept placeholder/empty test commands
        if commands == ["npm test"] and self._is_placeholder_test_suite(repo_path):
            self._logger.warning(
                "Placeholder or missing test suite detected in package.json. "
                "Falling back to syntax checking and boot check verification..."
            )
            return self._run_syntax_and_boot_checks(repo_path)

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

    def _is_placeholder_test_suite(self, repo_path: str) -> bool:
        pkg_json_path = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                import json
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Check scripts.test
                test_script = data.get("scripts", {}).get("test", "")
                if "no test specified" in test_script or not test_script.strip():
                    return True
                
                # Check if any standard test framework exists in dependencies/devDependencies
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                test_frameworks = ("jest", "mocha", "jasmine", "tape", "vitest", "ava", "cypress", "playwright")
                has_framework = any(
                    any(fw in dep for fw in test_frameworks)
                    for dep in (list(deps.keys()) + list(dev_deps.keys()))
                )
                if not has_framework:
                    return True
            except Exception:
                return True
        return False

    def _run_syntax_and_boot_checks(self, repo_path: str) -> VerificationResult:
        # 1. Syntax Check modified JS files
        modified_files = []
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                errors="replace",
            )
            for line in res.stdout.splitlines():
                if line.strip():
                    parts = line.strip().split()
                    if parts and parts[-1].endswith(".js"):
                        modified_files.append(parts[-1])
        except Exception:
            pass

        for f in modified_files:
            full_path = os.path.join(repo_path, f)
            if os.path.isfile(full_path):
                proc = subprocess.run(["node", "-c", f], cwd=repo_path, capture_output=True, text=True, errors="replace")
                if proc.returncode != 0:
                    return VerificationResult(
                        passed=False,
                        command=f"node -c {f}",
                        exit_code=proc.returncode,
                        stdout=proc.stdout,
                        stderr=proc.stderr,
                        error_summary=f"Syntax check failed in {f}:\n{proc.stderr or proc.stdout}",
                    )

        # 2. Boot Check
        entrypoint = "server.js"
        pkg_json = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json):
            try:
                import json
                with open(pkg_json, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                entrypoint = data.get("main", entrypoint)
            except Exception:
                pass
        
        entrypoint_path = os.path.join(repo_path, entrypoint)
        if not os.path.isfile(entrypoint_path):
            # Check common entrypoints
            for common in ("server.js", "app.js", "index.js"):
                if os.path.isfile(os.path.join(repo_path, common)):
                    entrypoint = common
                    break
        
        entrypoint_path = os.path.join(repo_path, entrypoint)
        if os.path.isfile(entrypoint_path):
            self._logger.progress(f"Running boot check: node {entrypoint} (2.0s)...")
            import time
            try:
                proc = subprocess.Popen(
                    ["node", entrypoint],
                    cwd=repo_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                )
                time.sleep(2.0)
                poll = proc.poll()
                if poll is not None and poll != 0:
                    stdout, stderr = proc.communicate()
                    return VerificationResult(
                        passed=False,
                        command=f"node {entrypoint}",
                        exit_code=poll,
                        stdout=stdout,
                        stderr=stderr,
                        error_summary=f"Entrypoint boot check crashed:\n{stderr or stdout}",
                    )
                else:
                    # Still running or completed successfully
                    proc.terminate()
                    proc.wait()
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    command=f"node {entrypoint}",
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    error_summary=f"Failed to start entrypoint: {e}",
                )

        return VerificationResult(
            passed=True,
            command="syntax + boot checks",
            exit_code=0,
            stdout="All syntax and boot checks passed successfully.",
            stderr="",
            error_summary="",
        )

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
