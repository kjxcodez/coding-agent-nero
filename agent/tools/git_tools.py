"""
Git inspection tools for viewing active diffs and repository status.
"""

import subprocess
from typing import Any, Dict, Optional

from ..config import AgentConfig
from .base import BaseTool
from .safety import ToolSafetyGuard


class GitDiffTool(BaseTool):
    """Tool for retrieving unified git diff of active modifications."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = repo_root
        self.memory = memory

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return "Show active git diff of staged, unstaged, and new files in repository."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(self, **kwargs) -> str:
        try:
            subprocess.run(["git", "add", "-N", "."], cwd=self.repo_root, check=False, capture_output=True)
            res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                errors="replace",
            )
            output = res.stdout.strip()
            return output if output else "(no changes detected in git diff)"
        except Exception as exc:
            return f"ERROR running git diff: {exc}"


class GitStatusTool(BaseTool):
    """Tool for retrieving git status file breakdown."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = repo_root
        self.memory = memory

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Show git status breakdown of modified, untracked, and staged files."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(self, **kwargs) -> str:
        try:
            res = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                errors="replace",
            )
            output = res.stdout.strip()
            return output if output else "(clean working tree, no modified or untracked files)"
        except Exception as exc:
            return f"ERROR running git status: {exc}"
