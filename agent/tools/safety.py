"""
Phase 4: Tool Safety Guard

Enforces strict security isolation boundaries for file access and shell commands.
Guarantees path traversal prevention and command allow-list enforcement.
"""

import os
import shlex
from typing import Tuple
from ..config import AgentConfig


class SecurityError(Exception):
    """Exception raised when a tool call violates security parameters."""
    pass


class ToolSafetyGuard:
    """Security sandbox validating path boundaries and command permissions."""

    def __init__(self, config: AgentConfig):
        self.config = config

    def resolve_and_validate_path(self, repo_root: str, relative_path: str) -> str:
        """
        Resolves relative path and verifies it strictly stays within the repo_root boundary.
        
        Raises:
            SecurityError if path escapes repo root or targets ignored directory.
        """
        abs_root = os.path.abspath(repo_root)
        
        # Clean relative path
        clean_path = relative_path.lstrip("/").lstrip("\\")
        target_path = os.path.abspath(os.path.join(abs_root, clean_path))

        # 1. Path Traversal Check (Must be subpath of abs_root)
        try:
            common = os.path.commonpath([abs_root, target_path])
            if common != abs_root:
                raise SecurityError(
                    f"Security Violation: Path '{relative_path}' resolves outside repository root ({abs_root})."
                )
        except ValueError:
            raise SecurityError(f"Security Violation: Invalid path resolution for '{relative_path}'.")

        # 2. Ignored Directories Check
        rel_from_root = os.path.relpath(target_path, abs_root)
        parts = rel_from_root.split(os.sep)
        if any(ignored in parts for ignored in self.config.ignored_dirs):
            raise SecurityError(
                f"Security Violation: Access to path '{relative_path}' is restricted (ignored directory)."
            )

        return target_path

    def validate_command(self, command: str) -> None:
        """
        Validates shell command against allow-listed commands or prefixes.
        
        Raises:
            SecurityError if command is forbidden or destructive.
        """
        cmd_str = command.strip()

        # Block dangerous subshell operators or pipe injections
        dangerous_operators = [";", "&&", "||", "|", "`", "$(", ">", "<", "\n"]
        for op in dangerous_operators:
            if op in cmd_str:
                raise SecurityError(f"Security Violation: Command contains forbidden operator '{op}': {cmd_str}")

        # Check against allowed prefixes
        allowed = False
        for prefix in self.config.allowed_command_prefixes:
            if cmd_str == prefix or cmd_str.startswith(prefix + " "):
                allowed = True
                break

        if not allowed:
            raise SecurityError(
                f"Security Violation: Command '{cmd_str}' is not allow-listed. "
                f"Allowed command prefixes: {list(self.config.allowed_command_prefixes)}"
            )
