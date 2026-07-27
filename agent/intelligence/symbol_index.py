"""
Symbol extraction — pluggable extractor architecture.
"""

from __future__ import annotations

import ast
import os
import re
from abc import ABC, abstractmethod
from typing import List, Optional

from ..config import AgentConfig
from .context import SymbolInfo, SymbolKind


class SymbolExtractor(ABC):
    """Abstract base for language-specific symbol extractors."""

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        ...

    @abstractmethod
    def extract(self, file_path: str, content: str) -> List[SymbolInfo]:
        ...


class PythonExtractor(SymbolExtractor):
    """Accurate Python symbol extraction using the standard library `ast` module."""

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith(".py")

    def extract(self, file_path: str, content: str) -> List[SymbolInfo]:
        symbols: List[SymbolInfo] = []
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(SymbolInfo(
                    name=node.name,
                    kind=SymbolKind.CLASS,
                    file=file_path,
                    line=node.lineno,
                    signature=f"class {node.name}",
                    docstring=ast.get_docstring(node) or "",
                    is_exported=not node.name.startswith("_"),
                ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = self._classify_function(node, tree)
                sig = self._build_signature(node)
                symbols.append(SymbolInfo(
                    name=node.name,
                    kind=kind,
                    file=file_path,
                    line=node.lineno,
                    signature=sig,
                    docstring=ast.get_docstring(node) or "",
                    is_exported=not node.name.startswith("_"),
                ))
        return symbols

    def _classify_function(self, node: ast.FunctionDef, tree: ast.AST) -> SymbolKind:
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                if node in ast.walk(parent):
                    return SymbolKind.METHOD
        return SymbolKind.FUNCTION

    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
        return f"{prefix} {node.name}({args})"


class JSFallbackExtractor(SymbolExtractor):
    """Conservative JS/TS symbol extractor using line-level patterns."""

    _RAW_PATTERNS = [
        (r"export\s+(?:default\s+)?(async\s+)?function\s+(\w+)\s*\(", SymbolKind.FUNCTION, 2),
        (r"(async\s+)?function\s+(\w+)\s*\(", SymbolKind.FUNCTION, 2),
        (r"(export\s+)?class\s+(\w+)", SymbolKind.CLASS, 2),
        (r"(const|let|var)\s+(\w+)\s*=\s*(async\s+)?\([^)]*\)\s*=>", SymbolKind.FUNCTION, 2),
        (r"(const|let|var)\s+(\w+)\s*=\s*(async\s+)?function\s*\(", SymbolKind.FUNCTION, 2),
        (r"module\.exports\.(\w+)\s*=", SymbolKind.EXPORT, 1),
        (r"exports\.(\w+)\s*=", SymbolKind.EXPORT, 1),
    ]

    def __init__(self) -> None:
        self._compiled = [
            (re.compile(pat), kind, group)
            for pat, kind, group in self._RAW_PATTERNS
        ]

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))

    def extract(self, file_path: str, content: str) -> List[SymbolInfo]:
        symbols: List[SymbolInfo] = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("*"):
                continue

            for pattern, kind, group in self._compiled:
                m = pattern.search(line)
                if m:
                    name = m.group(group)
                    symbols.append(SymbolInfo(
                        name=name,
                        kind=kind,
                        file=file_path,
                        line=i,
                        signature=stripped[:120],
                        is_exported=("export" in line or "module.exports" in line or "exports." in line),
                    ))
                    break
        return symbols


class FallbackExtractor(SymbolExtractor):
    """Stub extractor for all languages not yet supported."""

    def can_handle(self, file_path: str) -> bool:
        return True

    def extract(self, file_path: str, content: str) -> List[SymbolInfo]:
        return []


class SymbolIndexBuilder:
    """Builds a symbol index by dispatching files to the appropriate extractor."""

    MAX_FILE_SIZE = 500_000

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._registry: List[SymbolExtractor] = [
            PythonExtractor(),
            JSFallbackExtractor(),
            FallbackExtractor(),
        ]

    def _get_extractor(self, file_path: str) -> SymbolExtractor:
        for extractor in self._registry:
            if extractor.can_handle(file_path):
                return extractor
        return self._registry[-1]

    def build(self, files: List[str], repo_root: str) -> List[SymbolInfo]:
        symbols: List[SymbolInfo] = []
        for rel_path in files:
            abs_path = os.path.join(repo_root, rel_path)
            try:
                if os.path.getsize(abs_path) > self.MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            extractor = self._get_extractor(rel_path)
            try:
                extracted = extractor.extract(rel_path, content)
                symbols.extend(extracted)
            except Exception:
                continue

        return symbols
