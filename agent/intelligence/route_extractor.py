"""
Deterministic HTTP route extraction from source files.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from ..config import AgentConfig
from .context import RouteDefinition

# Express / Fastify: (router|app|fastify).(get|post|...)(path, ...)
_EXPRESS_PATTERN = re.compile(
    r"""(?:router|app|fastify|server)\s*\.\s*(get|post|put|patch|delete|all|head|options)"""
    r"""\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)

# FastAPI: @(app|router).(get|post|...)(path, ...)
_FASTAPI_PATTERN = re.compile(
    r"""@\s*(?:\w+\.)*(app|router|APIRouter\(\))\s*\.\s*(get|post|put|patch|delete|head|options)"""
    r"""\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

# Flask: @(app|bp|blueprint).(route|get|post|...)
_FLASK_PATTERN = re.compile(
    r"""@\s*(?:\w+\.)*(app|bp|blueprint|\w+)\s*\.\s*(?:route)\s*\(\s*['"]([^'"]+)['"].*?"""
    r"""(?:methods\s*=\s*\[([^\]]+)\])?""",
    re.IGNORECASE | re.DOTALL,
)

# Flask HTTP method shortcuts: @app.get, @app.post, etc.
_FLASK_METHOD_PATTERN = re.compile(
    r"""@\s*(?:\w+\.)*(app|bp|blueprint|\w+)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

# Django: path('route', view_func)
_DJANGO_PATTERN = re.compile(
    r"""(?:path|re_path)\s*\(\s*r?['"]([^'"]+)['"]\s*,\s*(\w+(?:\.\w+)*)""",
    re.IGNORECASE,
)


class RouteExtractor:
    """Extracts HTTP route definitions from repository source files."""

    MAX_FILE_SIZE = 200_000

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def extract(
        self,
        files: List[str],
        repo_root: str,
        frameworks: List[str],
    ) -> List[RouteDefinition]:
        routes: List[RouteDefinition] = []

        if "Next.js" in frameworks:
            routes.extend(self._extract_nextjs_routes(files))

        for rel_path in files:
            abs_path = os.path.join(repo_root, rel_path)

            try:
                if os.path.getsize(abs_path) > self.MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            ext = os.path.splitext(rel_path)[1].lower()
            is_js_ts = ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
            is_python = ext == ".py"

            if is_js_ts:
                try:
                    content = self._read_file(abs_path)
                except OSError:
                    continue

                if "Express.js" in frameworks or "Fastify" in frameworks:
                    routes.extend(self._extract_express(rel_path, content))

            elif is_python:
                try:
                    content = self._read_file(abs_path)
                except OSError:
                    continue

                if "FastAPI" in frameworks:
                    routes.extend(self._extract_fastapi(rel_path, content))

                if "Flask" in frameworks:
                    routes.extend(self._extract_flask(rel_path, content))

                if "Django" in frameworks:
                    basename = os.path.basename(rel_path).lower()
                    if "urls" in basename:
                        routes.extend(self._extract_django(rel_path, content))

        seen: set = set()
        unique: List[RouteDefinition] = []
        for r in routes:
            key = (r.method, r.path, r.file, r.line)
            if key not in seen:
                seen.add(key)
                unique.append(r)

        return unique

    def _extract_express(self, rel_path: str, content: str) -> List[RouteDefinition]:
        routes = []
        for i, line in enumerate(content.splitlines(), 1):
            m = _EXPRESS_PATTERN.search(line)
            if m:
                method = m.group(1).upper()
                path = m.group(2)
                handler = self._extract_handler_name(content, i)
                routes.append(RouteDefinition(
                    method=method,
                    path=path,
                    handler=handler or "(anonymous)",
                    file=rel_path,
                    line=i,
                ))
        return routes

    def _extract_fastapi(self, rel_path: str, content: str) -> List[RouteDefinition]:
        routes = []
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            m = _FASTAPI_PATTERN.search(line)
            if m:
                method = m.group(2).upper()
                path = m.group(3)
                handler = ""
                if i < len(lines):
                    next_line = lines[i].strip()
                    func_m = re.match(r"(?:async\s+)?def\s+(\w+)", next_line)
                    if func_m:
                        handler = func_m.group(1)
                routes.append(RouteDefinition(
                    method=method,
                    path=path,
                    handler=handler or "(anonymous)",
                    file=rel_path,
                    line=i,
                ))
        return routes

    def _extract_flask(self, rel_path: str, content: str) -> List[RouteDefinition]:
        routes = []
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            m = _FLASK_PATTERN.search(line)
            if m:
                path = m.group(2)
                methods_str = m.group(3)
                methods = (
                    [meth.strip().strip("'\"") for meth in methods_str.split(",")]
                    if methods_str
                    else ["GET"]
                )
                handler = ""
                if i < len(lines):
                    func_m = re.match(r"(?:async\s+)?def\s+(\w+)", lines[i].strip())
                    if func_m:
                        handler = func_m.group(1)
                for method in methods:
                    routes.append(RouteDefinition(
                        method=method.upper(),
                        path=path,
                        handler=handler or "(anonymous)",
                        file=rel_path,
                        line=i,
                    ))
                continue

            m2 = _FLASK_METHOD_PATTERN.search(line)
            if m2:
                method = m2.group(2).upper()
                path = m2.group(3)
                handler = ""
                if i < len(lines):
                    func_m = re.match(r"(?:async\s+)?def\s+(\w+)", lines[i].strip())
                    if func_m:
                        handler = func_m.group(1)
                routes.append(RouteDefinition(
                    method=method,
                    path=path,
                    handler=handler or "(anonymous)",
                    file=rel_path,
                    line=i,
                ))
        return routes

    def _extract_django(self, rel_path: str, content: str) -> List[RouteDefinition]:
        routes = []
        for i, line in enumerate(content.splitlines(), 1):
            m = _DJANGO_PATTERN.search(line)
            if m:
                path = m.group(1)
                handler = m.group(2)
                routes.append(RouteDefinition(
                    method="*",
                    path=path,
                    handler=handler,
                    file=rel_path,
                    line=i,
                ))
        return routes

    def _extract_nextjs_routes(self, files: List[str]) -> List[RouteDefinition]:
        routes = []
        for rel_path in files:
            norm = rel_path.replace("\\", "/")
            if "app/" in norm and norm.endswith(("/route.ts", "/route.js")):
                api_path = re.sub(r"^.*?app/", "/", norm)
                api_path = re.sub(r"/route\.(ts|js)$", "", api_path)
                api_path = re.sub(r"\[([^\]]+)\]", r":\1", api_path)
                routes.append(RouteDefinition(
                    method="ALL",
                    path=api_path,
                    handler="route handler",
                    file=rel_path,
                    line=1,
                ))
            elif "pages/api/" in norm and norm.endswith((".ts", ".js")):
                api_path = re.sub(r"^.*?pages", "", norm)
                api_path = re.sub(r"\.(ts|js)$", "", api_path)
                api_path = re.sub(r"\[([^\]]+)\]", r":\1", api_path)
                routes.append(RouteDefinition(
                    method="ALL",
                    path=api_path,
                    handler="API handler",
                    file=rel_path,
                    line=1,
                ))
        return routes

    def _read_file(self, abs_path: str) -> str:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()

    def _extract_handler_name(self, content: str, decorator_line: int) -> str:
        lines = content.splitlines()
        if decorator_line >= len(lines):
            return ""
        route_line = lines[decorator_line - 1]
        m = re.search(r",\s*(\w+)\s*[,)]", route_line)
        if m:
            candidate = m.group(1)
            if candidate not in {"req", "res", "next", "opts", "options"}:
                return candidate
        return ""
