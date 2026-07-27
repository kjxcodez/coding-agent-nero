"""
Environment variable detection for NERO's Repository Intelligence Layer.
"""

from __future__ import annotations

import os
import re
from typing import List, Set, Tuple

from ..config import AgentConfig

# .env file: KEY=value
_ENV_FILE_KEY = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)

# process.env.VARIABLE_NAME (JS/TS)
_JS_ENV_USAGE = re.compile(r"process\.env\.([A-Z][A-Z0-9_a-z]+)")

# os.environ['KEY'] (Python)
_PYTHON_ENVIRON = re.compile(r"""os\.environ(?:\.get)?\s*\(\s*['"]([^'"]+)['"]""")

# os.getenv('KEY') (Python)
_PYTHON_GETENV = re.compile(r"""os\.getenv\s*\(\s*['"]([^'"]+)['"]""")


class EnvScanner:
    """Scans a repository for environment variable declarations and usages."""

    TEMPLATE_NAMES: Tuple[str, ...] = (
        ".env.example",
        ".env.sample",
        ".env.template",
        ".env.defaults",
        ".env.test",
        ".env.development",
        ".env.production",
        ".env.staging",
        ".env.local",
    )

    MAX_SCAN_SIZE = 100_000

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def scan(self, files: List[str], repo_root: str) -> Tuple[List[str], List[str]]:
        env_files: List[str] = []
        env_var_names: Set[str] = set()

        for rel_path in files:
            basename = os.path.basename(rel_path)
            abs_path = os.path.join(repo_root, rel_path)

            is_env_file = basename.startswith(".env")
            if is_env_file:
                env_files.append(rel_path)
                if basename in self.TEMPLATE_NAMES or basename.endswith(
                    (".example", ".sample", ".template", ".defaults")
                ):
                    names = self._extract_env_file_keys(abs_path)
                    env_var_names.update(names)
                elif basename == ".env":
                    names = self._extract_env_file_keys(abs_path)
                    env_var_names.update(names)

            ext = os.path.splitext(rel_path)[1].lower()

            if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
                names = self._extract_js_env_usage(abs_path)
                env_var_names.update(names)
            elif ext == ".py":
                names = self._extract_python_env_usage(abs_path)
                env_var_names.update(names)

        return sorted(env_files), sorted(list(env_var_names))

    def _extract_env_file_keys(self, abs_path: str) -> Set[str]:
        names: Set[str] = set()
        try:
            size = os.path.getsize(abs_path)
            if size > self.MAX_SCAN_SIZE:
                return names
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for m in _ENV_FILE_KEY.finditer(content):
                names.add(m.group(1))
        except OSError:
            pass
        return names

    def _extract_js_env_usage(self, abs_path: str) -> Set[str]:
        names: Set[str] = set()
        try:
            size = os.path.getsize(abs_path)
            if size > self.MAX_SCAN_SIZE:
                return names
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for m in _JS_ENV_USAGE.finditer(content):
                names.add(m.group(1))
        except OSError:
            pass
        return names

    def _extract_python_env_usage(self, abs_path: str) -> Set[str]:
        names: Set[str] = set()
        try:
            size = os.path.getsize(abs_path)
            if size > self.MAX_SCAN_SIZE:
                return names
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for m in _PYTHON_ENVIRON.finditer(content):
                names.add(m.group(1))
            for m in _PYTHON_GETENV.finditer(content):
                names.add(m.group(1))
        except OSError:
            pass
        return names
