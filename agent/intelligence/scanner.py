"""
RepositoryScanner — primary orchestrator for the Repository Intelligence Layer.
Entry point for all repository analysis. Coordinates all sub-scanners and
returns a RepositoryContext that is cached for the current git HEAD.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from ..config import AgentConfig
from .cache import ContextCache
from .context import ArchitectureMap, RepositoryContext
from .detector import FrameworkDetector, LanguageDetector
from .env_scanner import EnvScanner
from .route_extractor import RouteExtractor
from .symbol_index import SymbolIndexBuilder


class RepositoryScanner:
    """
    Builds a RepositoryContext from a repository path.
    This class is the ONLY entry point for repository analysis.
    """

    SIZE_FULL        = 500
    SIZE_PROGRESSIVE = 5_000

    IGNORED_DIRS: Set[str] = {
        ".git", ".svn", ".hg",
        "node_modules", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".tox",
        "dist", "build", "out", ".next", ".nuxt", ".output",
        "coverage", ".nyc_output", "htmlcov",
        "venv", ".venv", "env", ".env_dir",
        "__generated__", "generated", ".turbo",
        ".cache", ".parcel-cache", "tmp", "temp",
        ".idea", ".vscode", ".DS_Store",
        "vendor",
    }

    IGNORED_EXTENSIONS: Set[str] = {
        ".pyc", ".pyo", ".pyd",
        "/.so", "/.dylib", ".dll", ".exe", ".o", ".obj",
        ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg", ".webp", ".avif",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
        ".mp4", ".mp3", ".avi", ".mov", ".wav",
        ".ttf", ".woff", ".woff2", ".eot",
        ".lock",
    }

    CONFIG_FILE_NAMES: Set[str] = {
        "package.json", "pyproject.toml", "setup.py", "setup.cfg",
        "Cargo.toml", "go.mod", "go.sum", "pom.xml",
        "build.gradle", "build.gradle.kts",
        "tsconfig.json", "jsconfig.json",
        "webpack.config.js", "vite.config.ts", "vite.config.js",
        "next.config.js", "next.config.ts", "next.config.mjs",
        "turbo.json", "lerna.json", "nx.json",
        "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
        ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
        ".prettierrc", ".prettierrc.json",
        "babel.config.js", "jest.config.js", "jest.config.ts",
        "vitest.config.ts", "vitest.config.js",
        ".gitignore", ".dockerignore",
        "Makefile", "makefile",
        "mypy.ini", ".mypy.ini", "pyrightconfig.json",
    }

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._cache         = ContextCache()
        self._lang_detector = LanguageDetector(config)
        self._fw_detector   = FrameworkDetector(config)
        self._route_extractor = RouteExtractor(config)
        self._env_scanner   = EnvScanner(config)
        self._symbol_builder = SymbolIndexBuilder(config)

    def scan(self, repo_path: str) -> RepositoryContext:
        abs_path = os.path.abspath(repo_path)
        if not os.path.isdir(abs_path):
            raise ValueError(f"Repository path does not exist: {abs_path}")

        cached = self._cache.load(abs_path)
        if cached is not None:
            return cached

        ctx = self._perform_scan(abs_path)
        self._cache.save(ctx)
        return ctx

    def rescan(self, repo_path: str) -> RepositoryContext:
        abs_path = os.path.abspath(repo_path)
        if not os.path.isdir(abs_path):
            raise ValueError(f"Repository path does not exist: {abs_path}")

        self._cache.invalidate(abs_path)
        ctx = self._perform_scan(abs_path)
        self._cache.save(ctx)
        return ctx

    def invalidate_cache(self, repo_path: str) -> None:
        abs_path = os.path.abspath(repo_path)
        self._cache.invalidate(abs_path)

    def _perform_scan(self, abs_path: str) -> RepositoryContext:
        all_files = self._walk_files(abs_path)
        total_files = len(all_files)

        git_commit, git_branch, git_dirty = self._get_git_info(abs_path)
        primary_lang, all_langs = self._lang_detector.detect(all_files)
        frameworks, databases, pkg_managers, build_tools = self._fw_detector.detect(all_files, abs_path)

        entrypoints       = self._find_entrypoints(all_files, primary_lang)
        models_files      = self._find_matching(all_files, ["model", "schema", "entity", "dto"])
        controllers_files = self._find_matching(all_files, ["controller", "route", "router", "api", "views", "view", "handler"])
        services_files    = self._find_matching(all_files, ["service", "repo", "repository", "dao", "store", "provider"])
        test_files        = self._find_matching(all_files, ["test", "spec", "__tests__", "tests"])
        config_files      = self._find_config_files(all_files)

        routes = self._route_extractor.extract(all_files, abs_path, frameworks)
        env_files, env_vars = self._env_scanner.scan(all_files, abs_path)

        arch_map = self._build_architecture_map(
            primary_lang, frameworks, entrypoints, controllers_files,
            services_files, models_files, test_files
        )

        symbols = []
        if total_files < self.SIZE_FULL:
            symbols = self._symbol_builder.build(all_files, abs_path)

        tree_snippet = self._generate_tree_snippet(all_files)

        return RepositoryContext(
            repo_path=abs_path,
            git_commit=git_commit,
            git_branch=git_branch,
            git_is_dirty=git_dirty,
            analysis_timestamp=datetime.now().isoformat(),
            primary_language=primary_lang,
            all_languages=all_langs,
            detected_frameworks=frameworks,
            package_managers=pkg_managers,
            databases_and_orms=databases,
            build_tools=build_tools,
            architecture_map=arch_map,
            entrypoints=entrypoints,
            config_files=config_files,
            env_files=env_files,
            env_variables=env_vars,
            file_tree_snippet=tree_snippet,
            total_files_count=total_files,
            routes=routes,
            models=models_files,
            controllers_or_routes=controllers_files,
            services_or_repos=services_files,
            test_files=test_files,
            components=[],
            symbols=symbols,
        )

    def _walk_files(self, root: str) -> List[str]:
        results: List[str] = []
        root_abs = os.path.abspath(root)

        for dirpath, dirnames, filenames in os.walk(root_abs):
            dirnames[:] = [d for d in dirnames if d not in self.IGNORED_DIRS and not d.startswith(".")]

            for filename in filenames:
                _, ext = os.path.splitext(filename)
                if ext in self.IGNORED_EXTENSIONS:
                    continue
                if filename.startswith(".") and filename not in {
                    ".env", ".env.example", ".env.sample", ".env.template",
                    ".gitignore", ".dockerignore", ".eslintrc.json",
                }:
                    continue

                abs_file = os.path.join(dirpath, filename)
                try:
                    rel = os.path.relpath(abs_file, root_abs).replace("\\", "/")
                    results.append(rel)
                except ValueError:
                    continue

        return results

    def _get_git_info(self, repo_path: str) -> Tuple[str, str, bool]:
        commit = self._run_git(repo_path, ["rev-parse", "HEAD"])
        branch = self._run_git(repo_path, ["branch", "--show-current"])
        status = self._run_git(repo_path, ["status", "--porcelain"])
        return (
            commit or "",
            branch or "unknown",
            bool(status),
        )

    def _run_git(self, repo_path: str, args: List[str]) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except Exception:
            pass
        return None

    def _find_matching(self, files: List[str], keywords: List[str]) -> List[str]:
        kw_lower = [k.lower() for k in keywords]
        return [f for f in files if any(kw in f.lower() for kw in kw_lower)]

    def _find_entrypoints(self, files: List[str], primary_lang: str) -> List[str]:
        entrypoint_names = {
            "index.js", "index.ts", "server.js", "server.ts",
            "app.js", "app.ts", "main.js", "main.ts",
            "entry.js", "entry.ts", "main.py", "app.py", "run.py", "server.py",
            "manage.py", "asgi.py", "wsgi.py", "Application.java", "Main.java",
            "main.go", "main.rs",
        }
        results = []
        for f in files:
            basename = os.path.basename(f)
            if basename in entrypoint_names:
                results.append(f)
        return results[:10]

    def _find_config_files(self, files: List[str]) -> List[str]:
        return [f for f in files if os.path.basename(f) in self.CONFIG_FILE_NAMES]

    def _build_architecture_map(
        self,
        primary_lang: str,
        frameworks: List[str],
        entrypoints: List[str],
        controllers: List[str],
        services: List[str],
        models: List[str],
        tests: List[str],
    ) -> ArchitectureMap:
        has_controllers = bool(controllers)
        has_services    = bool(services)
        has_models      = bool(models)
        has_tests       = bool(tests)
        fw_set          = set(frameworks)

        is_monorepo = any("packages/" in e or "apps/" in e for e in entrypoints)

        if is_monorepo:
            pattern = "Monorepo"
        elif len(frameworks) > 3:
            pattern = "Fullstack / Multi-Framework"
        elif has_controllers and has_services and has_models:
            pattern = "MVC / Layered Architecture"
        elif has_controllers and has_models:
            pattern = "MVC Architecture"
        elif "FastAPI" in fw_set or "Flask" in fw_set or "Express.js" in fw_set:
            pattern = "REST API"
        elif "Django" in fw_set:
            pattern = "MVC / Django (MTV)"
        elif "Next.js" in fw_set or "Nuxt" in fw_set:
            pattern = "Full-Stack Web Application"
        elif "React" in fw_set or "Vue" in fw_set or "Angular" in fw_set or "Svelte" in fw_set:
            pattern = "Frontend SPA"
        elif not frameworks:
            pattern = f"{primary_lang} Scripts / CLI"
        else:
            pattern = f"{primary_lang} Application"

        primary_fw = frameworks[0] if frameworks else primary_lang

        component_graph: Dict[str, List[str]] = {}
        if has_controllers:
            component_graph["controllers"] = controllers[:5]
        if has_services:
            component_graph["services"] = services[:5]
        if has_models:
            component_graph["models"] = models[:5]

        data_flow = self._describe_data_flow(pattern, frameworks, has_tests)

        return ArchitectureMap(
            pattern=pattern,
            primary_framework=primary_fw,
            component_graph=component_graph,
            data_flow_summary=data_flow,
        )

    def _describe_data_flow(self, pattern: str, frameworks: List[str], has_tests: bool) -> str:
        if "MVC" in pattern:
            return "Request → Controller → Service → Model → Database"
        if "REST API" in pattern:
            return "HTTP Request → Route Handler → Business Logic → Data Layer"
        if "Full-Stack" in pattern:
            return "Client → Server → API Routes → Data Layer"
        if "Frontend SPA" in pattern:
            return "User Interaction → Component → State → API Client"
        return "Input → Processing → Output"

    def _generate_tree_snippet(self, files: List[str], max_lines: int = 40) -> str:
        top_level: Dict[str, List[str]] = {}
        for f in files:
            parts = f.split("/")
            top = parts[0]
            if top not in top_level:
                top_level[top] = []
            if len(parts) == 1:
                top_level[top] = None

        lines = []
        for name in sorted(top_level.keys())[:max_lines]:
            if top_level[name] is None:
                lines.append(f"  {name}")
            else:
                lines.append(f"  {name}/")

        return "\n".join(lines)
