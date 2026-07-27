"""
Cloning and workspace loading tools.
"""

from typing import Any, Dict, Optional
from .base import BaseTool
from .safety import ToolSafetyGuard
from ..config import AgentConfig
from ..repo import RepositoryManager

class CloneRepoTool(BaseTool):
    """Tool for cloning a remote Git repository URL or binding a local directory."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = repo_root
        self.memory = memory

    @property
    def name(self) -> str:
        return "clone_repo"

    @property
    def description(self) -> str:
        return (
            "Clone a remote Git repository URL or bind a local workspace path to NERO. "
            "Pass Git https URL or local directory absolute path."
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url_or_path": {
                    "type": "string",
                    "description": "Git repository URL (https) or local absolute directory path.",
                }
            },
            "required": ["url_or_path"],
        }

    def execute(self, url_or_path: str, **kwargs) -> str:
        try:
            # Prepare repository is managed in AgentCore.repo_mgr            
            # Since prepare_repository is called in ensure_repository_context,
            # we update config.repo_path and memory.repo_path.
            if self.memory:
                self.memory.reset_for_new_repo()
                self.memory.repo_path = url_or_path
            
            self.config.repo_path = url_or_path
            
            # Trigger setup via running the manager
            mgr = RepositoryManager(self.config)
            actual_path = mgr.prepare_repository(url_or_path)
            
            if self.memory:
                self.memory.repo_path = actual_path
            
            return f"Successfully loaded and resolved workspace: {actual_path}"
        except Exception as exc:
            return f"ERROR loading repository '{url_or_path}': {exc}"
