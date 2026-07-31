"""
Deprecated compatibility shim.
"""

from .config import AgentConfig
from .intelligence.context import RepositoryContext
from .intelligence.scanner import RepositoryScanner


class RepositoryDiscovery:
    def __init__(self, config: AgentConfig) -> None:
        self._scanner = RepositoryScanner(config)

    def discover(self, repo_path: str) -> RepositoryContext:
        return self._scanner.scan(repo_path)
