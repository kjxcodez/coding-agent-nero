"""
Deterministic language and framework detection.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Set, Tuple

from ..config import AgentConfig


class LanguageDetector:
    """Counts source-code file extensions to determine the primary language."""

    SOURCE_EXTENSIONS: Dict[str, str] = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript (React)",
        ".js": "JavaScript",
        ".jsx": "JavaScript (React)",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".cs": "C#",
        ".php": "PHP",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".c": "C",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".kts": "Kotlin",
        ".scala": "Scala",
        ".r": "R",
        ".R": "R",
        ".ex": "Elixir",
        ".exs": "Elixir",
        ".erl": "Erlang",
        ".hs": "Haskell",
        ".lua": "Lua",
        ".dart": "Dart",
        ".vue": "Vue",
        ".svelte": "Svelte",
    }

    GENERATED_SUFFIXES: Tuple[str, ...] = (
        ".d.ts",
        ".min.js",
        ".min.css",
        ".bundle.js",
        ".chunk.js",
        "-lock.json",
        ".generated.ts",
        ".generated.js",
    )

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def detect(self, files: List[str]) -> Tuple[str, Dict[str, int]]:
        counts: Dict[str, int] = {}
        for f in files:
            if any(f.endswith(suffix) for suffix in self.GENERATED_SUFFIXES):
                continue
            _, ext = os.path.splitext(f)
            lang = self.SOURCE_EXTENSIONS.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1

        if not counts:
            return "Unknown", {}

        primary = max(counts, key=lambda k: counts[k])
        return primary, counts


_PYTHON_PACKAGE_MAP: Dict[str, Tuple[str, str]] = {
    "django": ("framework", "Django"),
    "fastapi": ("framework", "FastAPI"),
    "flask": ("framework", "Flask"),
    "starlette": ("framework", "Starlette"),
    "tornado": ("framework", "Tornado"),
    "aiohttp": ("framework", "aiohttp"),
    "litestar": ("framework", "Litestar"),
    "sanic": ("framework", "Sanic"),
    "sqlalchemy": ("database", "SQLAlchemy"),
    "psycopg2": ("database", "PostgreSQL (psycopg2)"),
    "psycopg2-binary": ("database", "PostgreSQL (psycopg2)"),
    "asyncpg": ("database", "PostgreSQL (asyncpg)"),
    "psycopg": ("database", "PostgreSQL (psycopg3)"),
    "pymongo": ("database", "MongoDB (pymongo)"),
    "motor": ("database", "MongoDB (motor)"),
    "redis": ("database", "Redis"),
    "aioredis": ("database", "Redis (async)"),
    "pymysql": ("database", "MySQL"),
    "aiomysql": ("database", "MySQL (async)"),
    "mysqlclient": ("database", "MySQL"),
    "tortoise-orm": ("database", "Tortoise ORM"),
    "beanie": ("database", "MongoDB (beanie)"),
    "alembic": ("database", "Alembic (migrations)"),
}


class FrameworkDetector:
    """Reads manifest files to detect frameworks, databases, and package managers."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def detect(
        self,
        files: List[str],
        repo_root: str,
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        frameworks: Set[str] = set()
        databases: Set[str] = set()
        pkg_managers: List[str] = []
        build_tools: List[str] = []

        if "package.json" in files:
            fw, db = self._parse_package_json(os.path.join(repo_root, "package.json"))
            frameworks.update(fw)
            databases.update(db)

            if "pnpm-lock.yaml" in files:
                pkg_managers.append("pnpm")
            elif "yarn.lock" in files:
                pkg_managers.append("yarn")
            elif "package-lock.json" in files:
                pkg_managers.append("npm")
            else:
                pkg_managers.append("npm")

        if "requirements.txt" in files:
            if "pip" not in pkg_managers:
                pkg_managers.append("pip")
            fw, db = self._parse_requirements_txt(os.path.join(repo_root, "requirements.txt"))
            frameworks.update(fw)
            databases.update(db)

        if "pyproject.toml" in files:
            if "poetry.lock" in files:
                pkg_managers.append("poetry")
            elif "pip" not in pkg_managers:
                pkg_managers.append("pip")
            fw, db = self._parse_pyproject_toml(os.path.join(repo_root, "pyproject.toml"))
            frameworks.update(fw)
            databases.update(db)

        if "Pipfile" in files and "pip" not in pkg_managers:
            pkg_managers.append("pipenv")

        if "Cargo.toml" in files:
            pkg_managers.append("cargo")
            build_tools.append("cargo")

        if "pom.xml" in files:
            pkg_managers.append("maven")
            fw, db = self._parse_pom_xml(os.path.join(repo_root, "pom.xml"))
            frameworks.update(fw)
            databases.update(db)

        if "build.gradle" in files or "build.gradle.kts" in files:
            pkg_managers.append("gradle")
            build_tools.append("gradle")

        if "go.mod" in files:
            pkg_managers.append("go modules")

        if "Makefile" in files or "makefile" in files:
            build_tools.append("make")
        if "turbo.json" in files:
            build_tools.append("turborepo")
        if "lerna.json" in files:
            build_tools.append("lerna")
        if "nx.json" in files:
            build_tools.append("nx")

        return (
            sorted(list(frameworks)),
            sorted(list(databases)),
            pkg_managers or ["standard"],
            build_tools,
        )

    def _parse_package_json(self, path: str) -> Tuple[Set[str], Set[str]]:
        frameworks: Set[str] = set()
        databases: Set[str] = set()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            deps: Dict[str, str] = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))
            deps.update(data.get("peerDependencies", {}))

            if "express" in deps:
                frameworks.add("Express.js")
            if "next" in deps:
                frameworks.add("Next.js")
            if "react" in deps or "react-dom" in deps:
                frameworks.add("React")
            if "@nestjs/core" in deps:
                frameworks.add("NestJS")
            if "fastify" in deps:
                frameworks.add("Fastify")
            if "koa" in deps:
                frameworks.add("Koa")
            if "vue" in deps:
                frameworks.add("Vue")
            if "svelte" in deps:
                frameworks.add("Svelte")

            if "mongoose" in deps:
                databases.add("Mongoose / MongoDB")
            if "@prisma/client" in deps or "prisma" in deps:
                databases.add("Prisma ORM")
            if "sequelize" in deps:
                databases.add("Sequelize ORM")
            if "typeorm" in deps:
                databases.add("TypeORM")
            if "drizzle-orm" in deps:
                databases.add("Drizzle ORM")
            if "pg" in deps:
                databases.add("PostgreSQL (pg)")
            if "redis" in deps or "ioredis" in deps:
                databases.add("Redis")
        except Exception:
            pass
        return frameworks, databases

    def _parse_requirements_txt(self, path: str) -> Tuple[Set[str], Set[str]]:
        frameworks: Set[str] = set()
        databases: Set[str] = set()
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    pkg_raw = re.split(r"[>=<!~\s\[\];@#]", line)[0].strip()
                    pkg_name = pkg_raw.lower().replace("_", "-")

                    if pkg_name in _PYTHON_PACKAGE_MAP:
                        kind, display = _PYTHON_PACKAGE_MAP[pkg_name]
                        if kind == "framework":
                            frameworks.add(display)
                        else:
                            databases.add(display)
        except Exception:
            pass
        return frameworks, databases

    def _parse_pyproject_toml(self, path: str) -> Tuple[Set[str], Set[str]]:
        frameworks: Set[str] = set()
        databases: Set[str] = set()
        dep_section_headers = {
            "[tool.poetry.dependencies]",
            "[tool.poetry.dev-dependencies]",
            "[project]",
            "[project.optional-dependencies]",
        }
        in_dep_section = False
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if line.startswith("["):
                        in_dep_section = line in dep_section_headers
                        continue
                    if not in_dep_section or not line or line.startswith("#"):
                        continue
                    m = re.match(r'^["\']?([A-Za-z0-9_\-]+)["\']?\s*(?:=|>=|<=|~=|!=|==|>|<)', line)
                    if m:
                        pkg_name = m.group(1).lower().replace("_", "-")
                        if pkg_name in _PYTHON_PACKAGE_MAP:
                            kind, display = _PYTHON_PACKAGE_MAP[pkg_name]
                            if kind == "framework":
                                frameworks.add(display)
                            else:
                                databases.add(display)
        except Exception:
            pass
        return frameworks, databases

    def _parse_pom_xml(self, path: str) -> Tuple[Set[str], Set[str]]:
        frameworks: Set[str] = set()
        databases: Set[str] = set()
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            artifact_ids = re.findall(r"<artifactId>([^<]+)</artifactId>", content)
            artifact_ids_lower = {a.lower() for a in artifact_ids}

            if any("spring-boot" in a for a in artifact_ids_lower):
                frameworks.add("Spring Boot")
            if any("spring-web" in a for a in artifact_ids_lower):
                frameworks.add("Spring MVC")
            if any("hibernate" in a for a in artifact_ids_lower):
                databases.add("Hibernate JPA")
            if any("postgresql" in a for a in artifact_ids_lower):
                databases.add("PostgreSQL")
        except Exception:
            pass
        return frameworks, databases
