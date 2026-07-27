"""
Canonical repository data models for NERO.
RepositoryContext is the single source of truth produced by the Repository Intelligence Layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SymbolKind(str, Enum):
    """Classification of a code symbol."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    EXPORT = "export"
    IMPORT = "import"
    ROUTE = "route"


@dataclass
class SymbolInfo:
    """A single named symbol extracted from a source file."""
    name: str
    kind: SymbolKind
    file: str           # relative path from repo root
    line: int
    signature: str = ""
    docstring: str = ""
    is_exported: bool = False
    references: List[str] = field(default_factory=list)  # "file:line" strings


@dataclass
class RouteDefinition:
    """A single HTTP route definition extracted from source code."""
    method: str     # GET | POST | PUT | PATCH | DELETE | ALL
    path: str       # e.g. /api/notes/:id
    handler: str    # function/controller name, if detectable
    file: str       # relative path from repo root
    line: int


@dataclass
class ArchitectureMap:
    """High-level architectural classification of the repository."""
    pattern: str                            # e.g. "MVC / REST API Layered"
    primary_framework: str
    component_graph: Dict[str, List[str]] = field(default_factory=dict)
    data_flow_summary: str = ""


@dataclass
class RepositoryContext:
    """Unified, persistent knowledge model of a target repository."""

    repo_path: str                          # absolute path
    git_commit: str = ""                    # HEAD SHA (empty if no git)
    git_branch: str = ""
    git_is_dirty: bool = False
    analysis_timestamp: str = ""

    primary_language: str = "Unknown"
    all_languages: Dict[str, int] = field(default_factory=dict)
    detected_frameworks: List[str] = field(default_factory=list)
    package_managers: List[str] = field(default_factory=list)
    databases_and_orms: List[str] = field(default_factory=list)
    build_tools: List[str] = field(default_factory=list)

    architecture_map: ArchitectureMap = field(
        default_factory=lambda: ArchitectureMap(
            pattern="Unknown", primary_framework="Unknown"
        )
    )

    entrypoints: List[str] = field(default_factory=list)
    config_files: List[str] = field(default_factory=list)
    env_files: List[str] = field(default_factory=list)
    env_variables: List[str] = field(default_factory=list)
    file_tree_snippet: str = ""
    total_files_count: int = 0

    routes: List[RouteDefinition] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    controllers_or_routes: List[str] = field(default_factory=list)
    services_or_repos: List[str] = field(default_factory=list)
    test_files: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)

    symbols: List[SymbolInfo] = field(default_factory=list)

    @property
    def candidate_edit_locations(self) -> List[str]:
        """Files most likely to need editing for a typical feature request."""
        return sorted(list(set(
            self.models[:5]
            + self.controllers_or_routes[:5]
            + self.services_or_repos[:5]
            + self.entrypoints[:3]
        )))

    def find_symbol(self, name: str) -> List[SymbolInfo]:
        """Case-insensitive symbol lookup in the index."""
        name_lower = name.lower()
        return [s for s in self.symbols if name_lower in s.name.lower()]

    def format_routes_summary(self) -> str:
        """Human-readable route table for LLM context injection."""
        if not self.routes:
            return "(no routes detected)"
        lines = [f"  {r.method:<7} {r.path:<40} → {r.handler} ({r.file}:{r.line})"
                 for r in self.routes[:20]]
        if len(self.routes) > 20:
            lines.append(f"  ... and {len(self.routes) - 20} more routes")
        return "\n".join(lines)

    def format_context_summary(self) -> str:
        """Rich context block injected into every LLM system message."""
        import os
        commit_short = self.git_commit[:7] if self.git_commit else "N/A"
        dirty_flag = " [DIRTY]" if self.git_is_dirty else ""
        langs = ", ".join(
            f"{lang}({count})" for lang, count in
            sorted(self.all_languages.items(), key=lambda x: -x[1])[:5]
        ) or self.primary_language

        lines = [
            "=== NERO Repository Intelligence ===",
            f"Workspace : [Root] {os.path.basename(self.repo_path)}",
            f"Branch    : {self.git_branch or 'N/A'}  |  Commit: {commit_short}{dirty_flag}",
            f"Language  : {self.primary_language}  ({langs})",
            f"Frameworks: {', '.join(self.detected_frameworks) or 'None detected'}",
            f"Databases : {', '.join(self.databases_and_orms) or 'None detected'}",
            f"Pkg Mgrs  : {', '.join(self.package_managers) or 'None'}",
            f"Arch      : {self.architecture_map.pattern}",
            f"Files     : {self.total_files_count}",
        ]

        if self.entrypoints:
            lines.append(f"Entrypoints: {', '.join(self.entrypoints[:5])}")

        if self.env_variables:
            lines.append(f"Env Vars  : {', '.join(self.env_variables[:15])}"
                         + (f" (+{len(self.env_variables)-15} more)" if len(self.env_variables) > 15 else ""))

        if self.routes:
            lines.append(f"\nAPI Routes ({len(self.routes)} detected):")
            lines.append(self.format_routes_summary())

        if self.symbols:
            lines.append(f"\nSymbol Index: {len(self.symbols)} symbols indexed")

        if self.file_tree_snippet:
            lines.append(f"\nFile Structure Preview:\n{self.file_tree_snippet}")

        return "\n".join(lines)
