"""
Configuration module for the NERO Autonomous AI Coding Agent.

Manages environmental variables, global configurations from ~/.nero/,
model routing defaults, safety parameters, and role-based fallback chains.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

# Global config directories
NERO_DIR = os.path.expanduser("~/.nero")
SETTINGS_PATH = os.path.join(NERO_DIR, "settings.json")
CREDENTIALS_PATH = os.path.join(NERO_DIR, "credentials.json")
LOGS_DIR = os.path.join(NERO_DIR, "logs")
SESSIONS_DIR = os.path.join(NERO_DIR, "sessions")
CACHE_DIR = os.path.join(NERO_DIR, "cache")


def ensure_nero_dirs():
    """Ensure that all NERO global subdirectories exist."""
    for d in [NERO_DIR, LOGS_DIR, SESSIONS_DIR, CACHE_DIR]:
        os.makedirs(d, exist_ok=True)


class ConfigValidationError(ValueError):
    """Raised when configuration fields fail validation checks."""

    pass


# Default configuration settings
DEFAULT_SETTINGS = {
    "planner_models": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "openai/gpt-4o-mini",
        "anthropic/claude-3-5-haiku-latest",
        "openrouter/free",
    ],
    "coder_models": [
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-latest",
        "openrouter/free",
    ],
    "verifier_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "openrouter/free"],
    "reviewer_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "openrouter/free"],
    "summary_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "openrouter/free"],
    "repo_path": "./target_repo",
    "max_iterations": 15,
    "max_repair_attempts": 3,
    "temperature": 0.1,
    "verbose": True,
}


def load_global_settings() -> Dict[str, Any]:
    """Loads configuration settings from ~/.nero/settings.json."""
    if not os.path.isfile(SETTINGS_PATH):
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge with defaults
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
    except Exception:
        return DEFAULT_SETTINGS


def load_global_credentials() -> Dict[str, str]:
    """Loads API credentials from ~/.nero/credentials.json."""
    if not os.path.isfile(CREDENTIALS_PATH):
        return {}
    try:
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# Load global configuration
ensure_nero_dirs()
_settings = load_global_settings()
_credentials = load_global_credentials()

# API Keys & Endpoints (Environment variables take precedence)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or _credentials.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or _credentials.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or _credentials.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or _credentials.get("GEMINI_API_KEY", "")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://github.com/")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "autonomous-coding-agent")


@dataclass
class AgentConfig:
    """Central configuration dataclass governing agent execution behavior."""

    # Model Fallback Chains per Role
    planner_models: List[str] = field(default_factory=lambda: list(_settings.get("planner_models", [])))
    coder_models: List[str] = field(default_factory=lambda: list(_settings.get("coder_models", [])))
    verifier_models: List[str] = field(default_factory=lambda: list(_settings.get("verifier_models", [])))
    reviewer_models: List[str] = field(default_factory=lambda: list(_settings.get("reviewer_models", [])))
    summary_models: List[str] = field(default_factory=lambda: list(_settings.get("summary_models", [])))

    # Operational Parameters
    repo_path: str = _settings.get("repo_path", "./target_repo")
    max_iterations: int = int(_settings.get("max_iterations", 15))
    max_repair_attempts: int = int(_settings.get("max_repair_attempts", 3))
    temperature: float = float(_settings.get("temperature", 0.1))
    verbose: bool = bool(_settings.get("verbose", True))

    # Verification overrides (set from CLI; None means use plan commands / auto-detect)
    verifier_command: str = ""  # If non-empty, used as the sole verification command
    skip_verification: bool = False  # If True, verification is skipped entirely

    # Security & Sandboxing Constraints
    ignored_dirs: Tuple[str, ...] = (
        ".git",
        "node_modules",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "coverage",
        ".idea",
        ".vscode",
    )
    max_read_bytes: int = 250_000

    # Command Execution Allow-list (Prefixes or full commands)
    allowed_command_prefixes: Tuple[str, ...] = (
        "npm test",
        "npm run test",
        "npm run build",
        "npm run lint",
        "npm install",
        "yarn test",
        "pnpm test",
        "pytest",
        "python -m unittest",
        "python3 -m unittest",
        "python -m pytest",
        "python3 -m pytest",
        "go test",
        "cargo test",
        "cargo check",
        "mvn test",
        "gradle test",
        "ruff check",
        "flake8",
        "black --check",
        "node -v",
        "python --version",
        "python3 --version",
        "node",
        "npx",
        "python",
        "python3",
        "jest",
        "vitest",
        "mocha",
        "eslint",
        "pip install",
        "pip3 install",
        "go run",
        "go build",
        "cargo run",
        "cargo build",
        "dotnet test",
        "dotnet build",
        "mvn compile",
        "gradle compileJava",
        "php -l",
        "ruby -c",
        "python -m compileall",
    )

    def validate(self) -> None:
        """Validates configuration parameters and raises ConfigValidationError on failure."""
        if not isinstance(self.planner_models, list) or not all(isinstance(m, str) and m for m in self.planner_models):
            raise ConfigValidationError("planner_models must be a list of non-empty strings.")
        if not isinstance(self.coder_models, list) or not all(isinstance(m, str) and m for m in self.coder_models):
            raise ConfigValidationError("coder_models must be a list of non-empty strings.")
        if not isinstance(self.verifier_models, list) or not all(
            isinstance(m, str) and m for m in self.verifier_models
        ):
            raise ConfigValidationError("verifier_models must be a list of non-empty strings.")
        if not isinstance(self.reviewer_models, list) or not all(
            isinstance(m, str) and m for m in self.reviewer_models
        ):
            raise ConfigValidationError("reviewer_models must be a list of non-empty strings.")
        if not isinstance(self.summary_models, list) or not all(isinstance(m, str) and m for m in self.summary_models):
            raise ConfigValidationError("summary_models must be a list of non-empty strings.")

        if not isinstance(self.repo_path, str) or not self.repo_path.strip():
            raise ConfigValidationError("repo_path must be a non-empty string.")

        if not isinstance(self.max_iterations, int) or self.max_iterations <= 0:
            raise ConfigValidationError(f"max_iterations must be a positive integer (got {self.max_iterations}).")
        if self.max_iterations > 100:
            raise ConfigValidationError(
                f"max_iterations is capped at 100 to prevent infinite loops (got {self.max_iterations})."
            )

        if not isinstance(self.max_repair_attempts, int) or self.max_repair_attempts < 0:
            raise ConfigValidationError(
                f"max_repair_attempts must be a non-negative integer (got {self.max_repair_attempts})."
            )
        if self.max_repair_attempts > 20:
            raise ConfigValidationError(f"max_repair_attempts is capped at 20 (got {self.max_repair_attempts}).")

        if not isinstance(self.temperature, (int, float)) or not (0.0 <= self.temperature <= 2.0):
            raise ConfigValidationError(f"temperature must be a float between 0.0 and 2.0 (got {self.temperature}).")

        if not isinstance(self.verbose, bool):
            raise ConfigValidationError(f"verbose must be a boolean (got {self.verbose}).")

        if not isinstance(self.verifier_command, str):
            raise ConfigValidationError("verifier_command must be a string.")

        if not isinstance(self.skip_verification, bool):
            raise ConfigValidationError(f"skip_verification must be a boolean (got {self.skip_verification}).")

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def with_single_model(cls, model: str, **kwargs) -> "AgentConfig":
        """Convenience factory to assign one model across all roles."""
        return cls(
            planner_models=[model],
            coder_models=[model],
            verifier_models=[model],
            reviewer_models=[model],
            summary_models=[model],
            **kwargs,
        )
