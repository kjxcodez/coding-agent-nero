"""
Tool System Package & Registry Dispatcher with SessionMemory/WorkingMemory integration.
"""

from typing import Any, Dict, List, Optional

from ..config import AgentConfig
from .base import BaseTool, ToolError
from .cmd_tools import RunCommandTool
from .fs_tools import CreateFileTool, ListFilesTool, ReadFileTool, ReplaceTextTool, WriteFileTool
from .git_tools import GitDiffTool, GitStatusTool
from .repo_tools import CloneRepoTool
from .safety import ToolSafetyGuard
from .search_tools import SearchCodeContentTool, SearchFilenamesTool, SearchRoutesTool, SearchSymbolsTool

# Interface compatibility shim
WorkingMemory = Any


class ToolRegistry:
    """Central registry and dispatch engine for agent tools."""

    def __init__(self, config: AgentConfig, repo_root: str, memory: Optional[WorkingMemory] = None):
        self.config = config
        self.repo_root = repo_root
        self.memory = memory
        self.safety = ToolSafetyGuard(config)

        # Register tools
        self._tools: Dict[str, BaseTool] = {}
        for tool_cls in [
            CloneRepoTool,
            ListFilesTool,
            ReadFileTool,
            WriteFileTool,
            CreateFileTool,
            ReplaceTextTool,
            SearchCodeContentTool,
            SearchFilenamesTool,
            SearchSymbolsTool,
            SearchRoutesTool,
            GitDiffTool,
            GitStatusTool,
            RunCommandTool,
        ]:
            t = tool_cls(self.config, self.safety, self.repo_root, memory=self.memory)
            self._tools[t.name] = t

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Returns list of OpenAI function schemas for registered tools."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Dispatches execution to matching registered tool."""
        if tool_name not in self._tools:
            return f"ERROR: Tool '{tool_name}' not found. Available tools: {list(self._tools.keys())}"

        tool = self._tools[tool_name]
        try:
            return tool.execute(**arguments)
        except Exception as exc:
            return f"ERROR executing tool '{tool_name}': {exc}"


__all__ = [
    "BaseTool",
    "ToolError",
    "ToolSafetyGuard",
    "ToolRegistry",
]
