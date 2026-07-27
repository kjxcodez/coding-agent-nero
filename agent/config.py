"""
Configuration module for the NERO Autonomous AI Coding Agent.

Manages environmental variables, global configurations from ~/.nero/,
model routing defaults, safety parameters, and role-based fallback chains.
"""

import os
import json
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any
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

# Default configuration settings
DEFAULT_SETTINGS = {
    "planner_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "openrouter/free"],
    "coder_models": ["google/gemini-2.5-flash", "openai/gpt-4o", "anthropic/claude-3-5-sonnet-latest"],
    "verifier_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini"],
    "reviewer_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini"],
    "summary_models": ["google/gemini-2.5-flash", "openai/gpt-4o-mini"],
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
    )

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
