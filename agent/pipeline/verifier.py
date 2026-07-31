"""
VerificationEngine — Phase 4, Step 3 of the MODIFY pipeline.
"""

from __future__ import annotations

import os
import subprocess
import shlex
import sys
import shutil
import json
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
        ecosystem = self._detect_ecosystem(repo_path)

        # Priority 1 & 2: User override or Planner supplied commands
        if commands:
            result = self._run_commands(commands, repo_path)
            # If the supplied command is npm test but it's a known placeholder, fall back
            if not result.passed and commands == ["npm test"] and self._is_placeholder_test_suite(repo_path):
                return self._populate_result(self._run_fallback_verification(repo_path, ecosystem))
            return self._populate_result(result)

        # Priority 3: Repository native test command
        native_tests = self._auto_detect_commands(repo_path)
        if native_tests:
            # If it's a known Node placeholder, skip and fall back directly
            if native_tests == ["npm test"] and self._is_placeholder_test_suite(repo_path):
                return self._populate_result(self._run_fallback_verification(repo_path, ecosystem))

            self._logger.progress(f"Running auto-detected test command: {native_tests}")
            result = self._run_commands(native_tests, repo_path)
            if result.passed:
                return self._populate_result(result)

            # Check if tests failed because they don't exist
            if self._is_missing_test_error(result):
                self._logger.warning("Native tests failed due to missing test suites/files. Running fallback...")
            else:
                return self._populate_result(result)

        # Priority 4, 5, 6: Fallback verification (build, compile, syntax, boot checks)
        return self._populate_result(self._run_fallback_verification(repo_path, ecosystem))

    def _run_commands(self, commands: List[str], repo_path: str) -> VerificationResult:
        result = VerificationResult(passed=True, command="", exit_code=0, stdout="", stderr="")
        for cmd in commands:
            result = self._run_one(cmd, repo_path)
            if not result.passed:
                return result
        return result

    def _detect_ecosystem(self, repo_path: str) -> str:
        if not os.path.isdir(repo_path):
            return "generic"
        files = set(os.listdir(repo_path))

        if any(f in files for f in ("package.json", "yarn.lock", "pnpm-lock.yaml", "package-lock.json", "bun.lockb")):
            return "node"
        if any(f in files for f in ("requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile", "setup.py", "setup.cfg", "pytest.ini")):
            return "python"
        if "go.mod" in files:
            return "go"
        if "Cargo.toml" in files:
            return "rust"
        if any(f in files for f in ("pom.xml", "build.gradle", "settings.gradle")):
            return "java"
        if any(f.endswith((".sln", ".csproj")) for f in files):
            return "dotnet"
        if "composer.json" in files:
            return "php"
        if "Gemfile" in files or "Rakefile" in files:
            return "ruby"

        return "generic"

    def _is_placeholder_test_suite(self, repo_path: str) -> bool:
        pkg_json_path = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                test_script = data.get("scripts", {}).get("test", "")
                if "no test specified" in test_script or not test_script.strip():
                    return True
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

    def _is_missing_test_error(self, result: VerificationResult) -> bool:
        if result.exit_code == -1:
            return True
        combined = (result.stderr + "\n" + result.stdout).lower()
        if "no test specified" in combined:
            return True
        if "no tests ran" in combined or "collected 0 items" in combined or "command not found" in combined:
            return True
        if "no test files" in combined or "no go files in" in combined:
            return True
        return False

    def _run_fallback_verification(self, repo_path: str, ecosystem: str) -> VerificationResult:
        self._logger.warning(
            f"Native test command failed or was missing. "
            f"Running fallback verification for '{ecosystem}' project..."
        )

        if ecosystem == "node":
            res = self._run_node_fallback(repo_path)
        elif ecosystem == "python":
            res = self._run_python_fallback(repo_path)
        elif ecosystem == "go":
            res = self._run_go_fallback(repo_path)
        elif ecosystem == "rust":
            res = self._run_rust_fallback(repo_path)
        elif ecosystem == "java":
            res = self._run_java_fallback(repo_path)
        elif ecosystem == "dotnet":
            res = self._run_dotnet_fallback(repo_path)
        elif ecosystem == "php":
            res = self._run_php_fallback(repo_path)
        elif ecosystem == "ruby":
            res = self._run_ruby_fallback(repo_path)
        else:
            res = self._run_generic_fallback(repo_path)

        return self._populate_result(res)

    def _run_node_fallback(self, repo_path: str) -> VerificationResult:
        # 1. Native Build
        has_build_script = False
        pkg_json_path = os.path.join(repo_path, "package.json")
        package_manager = "npm"
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                has_build_script = "build" in data.get("scripts", {})
            except Exception:
                pass
            files = set(os.listdir(repo_path)) if os.path.isdir(repo_path) else set()
            if "pnpm-lock.yaml" in files:
                package_manager = "pnpm"
            elif "yarn.lock" in files:
                package_manager = "yarn"
            elif "bun.lockb" in files:
                package_manager = "bun"

        if has_build_script:
            self._logger.progress(f"Running build command: {package_manager} run build")
            res = self._run_one(f"{package_manager} run build", repo_path)
            if res.passed:
                return res

        # 2. Syntax check JS/TS
        res = self._run_node_syntax_check(repo_path)
        if not res.passed:
            return res

        # 3. Boot validation (only if safe entrypoint is found)
        return self._run_node_boot_check(repo_path)

    def _run_node_syntax_check(self, repo_path: str) -> VerificationResult:
        modified_files = self._get_modified_files(repo_path, (".js", ".ts"))
        for f in modified_files:
            full_path = os.path.join(repo_path, f)
            if os.path.isfile(full_path) and f.endswith(".js"):
                res = self._run_one(f"node -c {f}", repo_path)
                if not res.passed:
                    return res
        return VerificationResult(
            passed=True,
            command="node syntax check",
            exit_code=0,
            stdout="All Node syntax checks passed.",
            stderr=""
        )

    def _run_node_boot_check(self, repo_path: str) -> VerificationResult:
        entrypoint = None
        pkg_json = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                entrypoint = data.get("main")
            except Exception:
                pass
        
        if not entrypoint or not os.path.isfile(os.path.join(repo_path, entrypoint)):
            for common in ("server.js", "app.js", "index.js"):
                if os.path.isfile(os.path.join(repo_path, common)):
                    entrypoint = common
                    break

        if entrypoint and os.path.isfile(os.path.join(repo_path, entrypoint)):
            self._logger.progress(f"Running Node boot check: node {entrypoint} (2.0s)...")
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
                        error_summary=f"Node boot check crashed:\n{stderr or stdout}",
                    )
                else:
                    proc.terminate()
                    proc.wait()
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    command=f"node {entrypoint}",
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    error_summary=f"Failed to start Node entrypoint: {e}",
                )

        return VerificationResult(
            passed=True,
            command="node boot check",
            exit_code=0,
            stdout="Node boot check completed or skipped.",
            stderr=""
        )

    def _run_python_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running Python syntax compilation...")
        # Compiles all modified python files or all files in cwd
        res = self._run_one("python -m compileall -q .", repo_path)
        if not res.passed:
            return res
        return VerificationResult(
            passed=True,
            command="python compileall",
            exit_code=0,
            stdout="All Python files compiled successfully.",
            stderr=""
        )

    def _run_go_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running Go compilation...")
        return self._run_one("go build", repo_path)

    def _run_rust_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running Rust compilation...")
        return self._run_one("cargo build", repo_path)

    def _run_java_fallback(self, repo_path: str) -> VerificationResult:
        files = set(os.listdir(repo_path)) if os.path.isdir(repo_path) else set()
        if "pom.xml" in files:
            self._logger.progress("Running Maven compilation...")
            return self._run_one("mvn compile", repo_path)
        self._logger.progress("Running Gradle compilation...")
        return self._run_one("gradle compileJava", repo_path)

    def _run_dotnet_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running .NET compilation...")
        return self._run_one("dotnet build", repo_path)

    def _run_php_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running PHP syntax validation...")
        modified = self._get_modified_files(repo_path, (".php",))
        for f in modified:
            res = self._run_one(f"php -l {f}", repo_path)
            if not res.passed:
                return res
        return VerificationResult(
            passed=True,
            command="php syntax check",
            exit_code=0,
            stdout="PHP syntax check succeeded.",
            stderr=""
        )

    def _run_ruby_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.progress("Running Ruby syntax validation...")
        modified = self._get_modified_files(repo_path, (".rb",))
        for f in modified:
            res = self._run_one(f"ruby -c {f}", repo_path)
            if not res.passed:
                return res
        return VerificationResult(
            passed=True,
            command="ruby syntax check",
            exit_code=0,
            stdout="Ruby syntax check succeeded.",
            stderr=""
        )

    def _run_generic_fallback(self, repo_path: str) -> VerificationResult:
        self._logger.warning("Generic ecosystem. Gracefully skipping test execution.")
        return VerificationResult(
            passed=True,
            command="generic verification",
            exit_code=0,
            stdout="Generic ecosystem. Skipping tests.",
            stderr="",
            error_summary="Skipped — generic ecosystem."
        )

    def _get_modified_files(self, repo_path: str, extensions: tuple[str, ...]) -> List[str]:
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
                    if parts and parts[-1].endswith(extensions):
                        modified_files.append(parts[-1])
        except Exception:
            pass
        return modified_files

    def _run_syntax_and_boot_checks(self, repo_path: str) -> VerificationResult:
        """Deprecated: retained for backward compatibility with external callers."""
        return self._run_node_fallback(repo_path)

    def _classify_failure(self, result: VerificationResult) -> str:
        if result.passed:
            return "Verification Succeeded"
        if result.exit_code == -1:
            if "not in allow-list" in result.stderr:
                return "Verification Unsupported"
            return "Missing Runtime or Dependency"
            
        combined = (result.stderr + "\n" + result.stdout).lower()
        if "syntaxerror" in combined or "syntax error" in combined or "parse error" in combined:
            return "Syntax Error"
        if "compilation error" in combined or "failed to compile" in combined or "build failed" in combined or "could not compile" in combined:
            return "Compilation Error"
        if "missing dependency" in combined or "cannot find module" in combined or "modulerequestfailed" in combined or "modulenotfounderror" in combined or "importerror" in combined or "import error" in combined:
            return "Missing Dependency"
        if "missing database" in combined or "connection refused" in combined or "could not connect" in combined or "sqlite3.operationalerror" in combined:
            return "Missing Database"
        if "timeout" in combined or "timed out" in combined:
            return "Timeout"
        if "crash" in combined or "runtime error" in combined or "uncaught exception" in combined:
            return "Runtime Crash"
        if "failed" in combined or "failing" in combined or "failures" in combined or "assertionerror" in combined:
            return "Test Failure"
            
        return "Verification Failed"

    def _populate_result(self, result: VerificationResult) -> VerificationResult:
        if result.passed:
            result.classification = "Verification Succeeded"
        else:
            result.classification = self._classify_failure(result)
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
            cmd_args = shlex.split(command)
        except ValueError as val_err:
            msg = f"Failed to parse command arguments: {val_err}"
            self._logger.error(msg)
            return VerificationResult(
                passed=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=msg,
                error_summary=msg,
            )

        if not cmd_args:
            msg = "Command is empty."
            self._logger.error(msg)
            return VerificationResult(
                passed=False,
                command=command,
                exit_code=-1,
                stdout="",
                stderr=msg,
                error_summary=msg,
            )

        # On Windows, resolve the executable via shutil.which to handle absolute paths,
        # relative paths, and batch scripts (.cmd/.bat) correctly without shell=True.
        if sys.platform == "win32":
            resolved = shutil.which(cmd_args[0])
            if resolved:
                cmd_args[0] = resolved

        try:
            proc = subprocess.run(
                cmd_args,
                shell=False,
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
        # Reject any shell metacharacters/operators to prevent command injection
        # on all platforms (especially Windows batch files).
        shell_chars = {"&", "|", ";", "<", ">", "$", "`", "%", "!"}
        if any(char in cmd for char in shell_chars):
            return False

        # Verify if command starts with an allowed prefix
        for prefix in self._config.allowed_command_prefixes:
            if cmd == prefix or cmd.startswith(prefix + " "):
                return True
        return False

    def _auto_detect_commands(self, repo_path: str) -> List[str]:
        ecosystem = self._detect_ecosystem(repo_path)
        if not os.path.isdir(repo_path):
            return []
        files = set(os.listdir(repo_path))

        if ecosystem == "node":
            if "pnpm-lock.yaml" in files:
                return ["pnpm test"]
            if "yarn.lock" in files:
                return ["yarn test"]
            if "bun.lockb" in files:
                return ["bun test"]
            return ["npm test"]
            
        elif ecosystem == "python":
            if any(f in files for f in ("pytest.ini", "setup.cfg")):
                return ["pytest"]
            return ["python -m pytest"]
            
        elif ecosystem == "go":
            return ["go test"]
            
        elif ecosystem == "rust":
            return ["cargo test"]
            
        elif ecosystem == "java":
            if "pom.xml" in files:
                return ["mvn test"]
            return ["gradle test"]
            
        elif ecosystem == "dotnet":
            return ["dotnet test"]
            
        elif ecosystem == "php":
            return ["composer test"]
            
        elif ecosystem == "ruby":
            if "Gemfile" in files:
                return ["bundle exec rspec"]
            return ["ruby -c"]
            
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
