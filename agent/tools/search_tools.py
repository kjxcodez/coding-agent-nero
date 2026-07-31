"""
Search tools for querying codebase patterns via regex content matching, filename matching, symbol index querying, and route lookup.
"""

import fnmatch
import os
import re
from typing import Any, Dict, Optional

from ..config import AgentConfig
from .base import BaseTool, ToolError
from .safety import SecurityError, ToolSafetyGuard


class SearchCodeContentTool(BaseTool):
    """Search codebase files for content matching regex or substring pattern."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "search_code_content"

    @property
    def description(self) -> str:
        return "Search file contents within the repository for a regex or substring pattern."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex or substring content pattern to look for."},
                "path": {
                    "type": "string",
                    "description": "Directory relative to repo root to search. Defaults to '.'.",
                },
                "file_filter": {
                    "type": "string",
                    "description": "Optional glob filter for filenames (e.g. '*.py' or '*.ts').",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, pattern: str, path: str = ".", file_filter: Optional[str] = None, **kwargs) -> str:
        try:
            target_dir = self.safety.resolve_and_validate_path(self.repo_root, path)
            if not os.path.isdir(target_dir):
                raise ToolError(f"Search target path is not a directory: {path}")

            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ToolError(f"Invalid regex pattern '{pattern}': {exc}")

            matches = []
            max_matches = 100

            for root, dirs, files in os.walk(target_dir):
                dirs[:] = [d for d in dirs if d not in self.config.ignored_dirs]
                rel_root = os.path.relpath(root, self.repo_root)
                if any(ignored in rel_root.split(os.sep) for ignored in self.config.ignored_dirs):
                    continue

                for f in files:
                    # Apply file filter if specified
                    if file_filter and not fnmatch.fnmatch(f, file_filter):
                        continue

                    full_file = os.path.join(root, f)
                    rel_file = os.path.relpath(full_file, self.repo_root).replace(os.sep, "/")

                    if os.path.getsize(full_file) > self.config.max_read_bytes:
                        continue

                    try:
                        with open(full_file, "r", encoding="utf-8", errors="ignore") as fh:
                            for idx, line in enumerate(fh, 1):
                                if regex.search(line):
                                    matches.append(f"{rel_file}:{idx}:{line.strip()}")
                                    if len(matches) >= max_matches:
                                        break
                    except Exception:
                        continue

                    if len(matches) >= max_matches:
                        break
                if len(matches) >= max_matches:
                    break

            if not matches:
                return f"(no matches found for pattern '{pattern}')"

            result = "\n".join(matches)
            if len(matches) >= max_matches:
                result += f"\n... (capped at {max_matches} matches)"
            return result

        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class SearchFilenamesTool(BaseTool):
    """Search directory structure for files matching a glob or pattern."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "search_filenames"

    @property
    def description(self) -> str:
        return "Search the repository for file names matching a glob pattern or string."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob or text pattern to match filenames against (e.g. '*controller*').",
                },
                "path": {
                    "type": "string",
                    "description": "Directory relative to repo root to search under. Defaults to '.'.",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, pattern: str, path: str = ".", **kwargs) -> str:
        try:
            target_dir = self.safety.resolve_and_validate_path(self.repo_root, path)
            if not os.path.isdir(target_dir):
                raise ToolError(f"Search target path is not a directory: {path}")

            matches = []
            max_matches = 100

            for root, dirs, files in os.walk(target_dir):
                dirs[:] = [d for d in dirs if d not in self.config.ignored_dirs]
                rel_root = os.path.relpath(root, self.repo_root)
                if any(ignored in rel_root.split(os.sep) for ignored in self.config.ignored_dirs):
                    continue

                for f in files:
                    rel_file = os.path.relpath(os.path.join(root, f), self.repo_root).replace(os.sep, "/")
                    # Check match against filename or full path
                    if (
                        fnmatch.fnmatch(f, pattern)
                        or fnmatch.fnmatch(rel_file, pattern)
                        or pattern.lower() in f.lower()
                    ):
                        matches.append(rel_file)
                        if len(matches) >= max_matches:
                            break
                if len(matches) >= max_matches:
                    break

            if not matches:
                return f"(no matching files found for pattern '{pattern}')"

            result = "\n".join(matches)
            if len(matches) >= max_matches:
                result += f"\n... (capped at {max_matches} matches)"
            return result

        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class SearchSymbolsTool(BaseTool):
    """Query the indexed code symbols (classes, functions, methods)."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "search_symbols"

    @property
    def description(self) -> str:
        return "Search the repository symbol index for class, function, or method definitions."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact or partial name of the symbol (class/function/method) to look up.",
                }
            },
            "required": ["name"],
        }

    def execute(self, name: str, **kwargs) -> str:
        if not self.memory or not self.memory.repo_context:
            return "ERROR: Symbol index is not initialized. Code context must be scanned first."

        ctx = self.memory.repo_context
        matches = ctx.find_symbol(name)
        if not matches:
            # Try partial matching
            matches = [sym for sym in ctx.symbols if name.lower() in sym.name.lower()]

        if not matches:
            return f"(no symbols found matching name '{name}')"

        lines = []
        for sym in matches[:20]:
            lines.append(f"{sym.kind.value} {sym.name} defined in {sym.file}:{sym.line}")
            if sym.signature:
                lines.append(f"  Signature: {sym.signature}")
            if sym.docstring:
                lines.append(f"  Docstring: {sym.docstring[:150]}...")

        result = "\n".join(lines)
        if len(matches) > 20:
            result += f"\n... (and {len(matches) - 20} more symbols)"
        return result


class SearchRoutesTool(BaseTool):
    """Query framework-detected API endpoints / web routes."""

    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "search_routes"

    @property
    def description(self) -> str:
        return "Search the detected HTTP API / web endpoints and route handlers in the repository."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Substring pattern to filter routes by (e.g. '/api/users').",
                }
            },
        }

    def execute(self, pattern: Optional[str] = None, **kwargs) -> str:
        if not self.memory or not self.memory.repo_context:
            return "ERROR: Route index is not initialized. Code context must be scanned first."

        ctx = self.memory.repo_context
        routes = ctx.routes
        if not routes:
            return "(no HTTP routes detected in the repository)"

        if pattern:
            filtered = [r for r in routes if pattern.lower() in r.path.lower() or pattern.lower() in r.handler.lower()]
        else:
            filtered = routes

        if not filtered:
            return f"(no routes match pattern '{pattern}')"

        lines = [f"| {'Method':<7} | {'Path':<40} | {'Handler':<25} | {'Location':<20} |"]
        lines.append(f"|{'-' * 9}|{'-' * 42}|{'-' * 27}|{'-' * 22}|")

        for r in filtered[:30]:
            lines.append(f"| {r.method:<7} | {r.path:<40} | {r.handler:<25} | {r.file}:{r.line:<5} |")

        result = "\n".join(lines)
        if len(filtered) > 30:
            result += f"\n... (and {len(filtered) - 30} more routes)"
        return result
