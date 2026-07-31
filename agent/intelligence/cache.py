"""
Repository Intelligence Cache.
Caches scanned repository context in the user's global ~/.nero/cache/ directory.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from typing import Optional

from ..config import CACHE_DIR
from .context import (
    ArchitectureMap,
    RepositoryContext,
    RouteDefinition,
    SymbolInfo,
    SymbolKind,
)


class ContextCache:
    """On-disk cache for RepositoryContext, keyed by repo path + git HEAD."""

    STALE_AFTER_DAYS = 30

    def __init__(self) -> None:
        self._base = CACHE_DIR

    def load(self, abs_repo_path: str) -> Optional[RepositoryContext]:
        git_commit = self._get_git_head(abs_repo_path)
        if not git_commit:
            return None

        cache_file = self._cache_path(abs_repo_path, git_commit)
        if not os.path.isfile(cache_file):
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ctx = self._deserialise(data)
            return ctx
        except Exception:
            return None

    def save(self, ctx: RepositoryContext) -> None:
        if not ctx.git_commit:
            return

        try:
            cache_file = self._cache_path(ctx.repo_path, ctx.git_commit)
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as fh:
                json.dump(self._serialise(ctx), fh, indent=2)
        except Exception:
            pass

    def invalidate(self, abs_repo_path: str) -> None:
        prefix = hashlib.sha256(abs_repo_path.encode()).hexdigest()[:8]
        try:
            for fname in os.listdir(self._base):
                if fname.startswith(prefix):
                    os.remove(os.path.join(self._base, fname))
        except (OSError, FileNotFoundError):
            pass

    def purge_stale(self) -> int:
        cutoff = datetime.now() - timedelta(days=self.STALE_AFTER_DAYS)
        deleted = 0
        try:
            for fname in os.listdir(self._base):
                fpath = os.path.join(self._base, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if mtime < cutoff:
                        os.remove(fpath)
                        deleted += 1
                except OSError:
                    continue
        except (OSError, FileNotFoundError):
            pass
        return deleted

    def _cache_path(self, abs_repo_path: str, git_commit: str) -> str:
        raw_key = f"{abs_repo_path}:{git_commit}"
        short_key = hashlib.sha256(raw_key.encode()).hexdigest()[:16]
        return os.path.join(self._base, f"{short_key}.json")

    def _get_git_head(self, repo_path: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _serialise(self, ctx: RepositoryContext) -> dict:
        return dataclasses.asdict(ctx)

    def _deserialise(self, data: dict) -> RepositoryContext:
        arch_raw = data.get("architecture_map", {})
        arch_map = ArchitectureMap(
            pattern=arch_raw.get("pattern", "Unknown"),
            primary_framework=arch_raw.get("primary_framework", "Unknown"),
            component_graph=arch_raw.get("component_graph", {}),
            data_flow_summary=arch_raw.get("data_flow_summary", ""),
        )

        routes = [RouteDefinition(**r) for r in data.get("routes", [])]

        symbols = []
        for s in data.get("symbols", []):
            try:
                symbols.append(
                    SymbolInfo(
                        name=s["name"],
                        kind=SymbolKind(s["kind"]),
                        file=s["file"],
                        line=s["line"],
                        signature=s.get("signature", ""),
                        docstring=s.get("docstring", ""),
                        is_exported=s.get("is_exported", False),
                        references=s.get("references", []),
                    )
                )
            except (KeyError, ValueError):
                continue

        return RepositoryContext(
            repo_path=data["repo_path"],
            git_commit=data.get("git_commit", ""),
            git_branch=data.get("git_branch", ""),
            git_is_dirty=data.get("git_is_dirty", False),
            analysis_timestamp=data.get("analysis_timestamp", ""),
            primary_language=data.get("primary_language", "Unknown"),
            all_languages=data.get("all_languages", {}),
            detected_frameworks=data.get("detected_frameworks", []),
            package_managers=data.get("package_managers", []),
            databases_and_orms=data.get("databases_and_orms", []),
            build_tools=data.get("build_tools", []),
            architecture_map=arch_map,
            entrypoints=data.get("entrypoints", []),
            config_files=data.get("config_files", []),
            env_files=data.get("env_files", []),
            env_variables=data.get("env_variables", []),
            file_tree_snippet=data.get("file_tree_snippet", ""),
            total_files_count=data.get("total_files_count", 0),
            routes=routes,
            models=data.get("models", []),
            controllers_or_routes=data.get("controllers_or_routes", []),
            services_or_repos=data.get("services_or_repos", []),
            test_files=data.get("test_files", []),
            components=data.get("components", []),
            symbols=symbols,
        )
