"""
Command execution tools for running safe, allow-listed test and build commands.
"""

import subprocess
from typing import Any, Dict, Optional
from .base import BaseTool, ToolError
from .safety import ToolSafetyGuard, SecurityError
from ..config import AgentConfig


class RunCommandTool(BaseTool):
    """Executes sandboxed allow-listed build and verification shell commands."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = repo_root
        self.memory = memory

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "Run an allow-listed build or test command in repository root "
            "(e.g., 'npm test', 'pytest', 'npm run build'). Restricted command shell."
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command string to execute."}
            },
            "required": ["command"],
        }

    def execute(self, command: str, **kwargs) -> str:
        try:
            # Enforce safety validation
            self.safety.validate_command(command)

            print(f"  [Executing Safe Command]: '{command}'")
            res = subprocess.run(
                command,
                cwd=self.repo_root,
                shell=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=120,
            )

            out = (res.stdout or "") + (res.stderr or "")
            truncated_out = out[-4000:] if len(out) > 4000 else out
            return f"exit_code={res.returncode}\nOutput:\n{truncated_out}"
        except SecurityError as exc:
            return f"ERROR (Security Violation): {exc}"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command '{command}' timed out after 120 seconds."
        except Exception as exc:
            return f"ERROR running command '{command}': {exc}"
