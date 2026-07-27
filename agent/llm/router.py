"""
Model Router managing role-based model dispatching and ordered fallback chains across providers.
"""

import logging
from typing import Any, Dict, List, Optional
from .base import LLMProvider, LLMResponse
from ..config import AgentConfig

_log = logging.getLogger(__name__)


class ModelRouter:
    """Dispatches chat completions across model fallback chains per role."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._providers: Dict[str, LLMProvider] = {}

    def _get_provider_for_model(self, model: str) -> LLMProvider:
        """Determines the correct provider adapter for a model name and caches it."""
        if model.startswith("openrouter/"):
            provider_key = "openrouter"
        elif model.startswith("openai/") or model.startswith("gpt-"):
            provider_key = "openai"
        elif model.startswith("google/") or model.startswith("gemini-"):
            provider_key = "google"
        elif model.startswith("anthropic/") or model.startswith("claude-"):
            provider_key = "anthropic"
        else:
            # Fallback to whatever provider has a configured API key
            from .. import config as cfg
            if cfg.GEMINI_API_KEY:
                provider_key = "google"
            elif cfg.OPENAI_API_KEY:
                provider_key = "openai"
            elif cfg.ANTHROPIC_API_KEY:
                provider_key = "anthropic"
            else:
                provider_key = "openrouter"

        if provider_key not in self._providers:
            from .providers import OpenAIProvider, OpenRouterProvider, GeminiProvider, AnthropicProvider
            if provider_key == "openrouter":
                self._providers[provider_key] = OpenRouterProvider()
            elif provider_key == "openai":
                self._providers[provider_key] = OpenAIProvider()
            elif provider_key == "google":
                self._providers[provider_key] = GeminiProvider()
            elif provider_key == "anthropic":
                self._providers[provider_key] = AnthropicProvider()

        return self._providers[provider_key]

    def _get_models_for_role(self, role: str) -> List[str]:
        mapping = {
            "planner": self.config.planner_models,
            "coder": self.config.coder_models,
            "verifier": self.config.verifier_models,
            "reviewer": self.config.reviewer_models,
            "summary": self.config.summary_models,
        }
        if role not in mapping:
            raise ValueError(f"Unknown role '{role}'. Valid roles: {list(mapping.keys())}")
        return mapping[role]

    def chat(
        self,
        role: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Attempts execution using the fallback model chain for the given role.
        
        Args:
            role: The agent role ('planner', 'coder', 'verifier', 'reviewer', 'summary').
            messages: Conversation messages list.
            tools: Optional tool schemas.
            tool_choice: Optional tool choice setting.
            stream: Whether to stream the response.

        Returns:
            LLMResponse from the first successful model attempt.
        """
        models = self._get_models_for_role(role)
        last_error: Optional[Exception] = None

        for model in models:
            try:
                provider = self._get_provider_for_model(model)
                response = provider.generate(
                    model=model,
                    messages=messages,
                    temperature=self.config.temperature,
                    tools=tools,
                    tool_choice=tool_choice,
                    stream=stream,
                )
                return response
            except Exception as exc:
                _log.warning(
                    "Model '%s' failed for role '%s': %s", model, role, exc
                )
                last_error = exc
                continue

        raise RuntimeError(
            f"All models failed for role '{role}': {models}. Last error: {last_error}"
        )
