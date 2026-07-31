"""
Unit tests for ModelRouter tool calling fallback mechanism (ModelRouter.chat).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agent.config import AgentConfig
from agent.llm.base import LLMResponse
from agent.llm.router import ModelRouter


class TestRouterFallback(unittest.TestCase):
    def test_fallback_when_tool_calling_fails(self):
        """If tool-use completions fail, ModelRouter must fallback to non-tool completion."""
        config = AgentConfig()
        router = ModelRouter(config)

        # Mock the provider
        mock_provider = MagicMock()

        # Side effect: first call with tools raises exception, second call without tools succeeds
        def mock_generate(model, messages, temperature, tools=None, tool_choice=None, stream=False):
            if tools is not None:
                raise ValueError("model emitted an undeclared tool call")
            return LLMResponse(content="Hello from text fallback!", tool_calls=[], model_used=model)

        mock_provider.generate.side_effect = mock_generate

        with patch.object(router, "_get_provider_for_model", return_value=mock_provider):
            res = router.chat(
                role="coder",
                messages=[{"role": "user", "content": "run the server"}],
                tools=[{"type": "function", "function": {"name": "run_command"}}],
            )
            self.assertEqual(res.content, "Hello from text fallback!")
            self.assertEqual(mock_provider.generate.call_count, 2)

    def test_no_fallback_when_no_tools_passed(self):
        """If no tools were originally passed, a failure should not trigger fallback retries."""
        config = AgentConfig()
        router = ModelRouter(config)

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = ValueError("API Error")

        with patch.object(router, "_get_provider_for_model", return_value=mock_provider):
            with self.assertRaises(RuntimeError):
                router.chat(role="coder", messages=[{"role": "user", "content": "hello"}], tools=None)
            # Only tried once per model in fallback chain
            self.assertEqual(mock_provider.generate.call_count, len(config.coder_models))


if __name__ == "__main__":
    unittest.main()
