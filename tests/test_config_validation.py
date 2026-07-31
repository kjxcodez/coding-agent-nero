"""
Unit tests for configuration validation system and model cleanup (P2.2).
"""

from __future__ import annotations

import unittest
from agent.config import AgentConfig, ConfigValidationError


class TestConfigValidation(unittest.TestCase):

    def test_default_config_is_valid(self):
        """Default configuration must pass validation successfully."""
        config = AgentConfig()
        self.assertEqual(config.max_iterations, 15)
        self.assertEqual(config.max_repair_attempts, 3)
        self.assertEqual(config.temperature, 0.1)
        self.assertTrue(config.verbose)

    def test_invalid_max_iterations(self):
        """Validation must reject zero, negative, or excessive max_iterations values."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(max_iterations=0)

        with self.assertRaises(ConfigValidationError):
            AgentConfig(max_iterations=-5)

        with self.assertRaises(ConfigValidationError):
            AgentConfig(max_iterations=101)  # capped at 100

    def test_invalid_max_repair_attempts(self):
        """Validation must reject negative or excessive max_repair_attempts values."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(max_repair_attempts=-1)

        with self.assertRaises(ConfigValidationError):
            AgentConfig(max_repair_attempts=21)  # capped at 20

    def test_invalid_temperature(self):
        """Validation must reject temperatures outside the 0.0 - 2.0 range or of wrong type."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(temperature=-0.1)

        with self.assertRaises(ConfigValidationError):
            AgentConfig(temperature=2.1)

        with self.assertRaises(ConfigValidationError):
            # No-op type check
            AgentConfig(temperature="warm")

    def test_invalid_verbose(self):
        """Validation must reject non-boolean verbose settings."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(verbose="yes")

    def test_invalid_models_list(self):
        """Validation must reject non-list model configurations or lists containing empty/non-string values."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(planner_models="gemini-flash")

        with self.assertRaises(ConfigValidationError):
            AgentConfig(coder_models=[""])

        with self.assertRaises(ConfigValidationError):
            AgentConfig(coder_models=[123])

    def test_invalid_repo_path(self):
        """Validation must reject empty or blank repository paths."""
        with self.assertRaises(ConfigValidationError):
            AgentConfig(repo_path="")

        with self.assertRaises(ConfigValidationError):
            AgentConfig(repo_path="   ")

    def test_with_single_model_factory(self):
        """with_single_model must correctly populate model chains and validate successfully."""
        config = AgentConfig.with_single_model("openai/gpt-4o")
        self.assertEqual(config.planner_models, ["openai/gpt-4o"])
        self.assertEqual(config.coder_models, ["openai/gpt-4o"])
        self.assertEqual(config.verifier_models, ["openai/gpt-4o"])
        self.assertEqual(config.reviewer_models, ["openai/gpt-4o"])
        self.assertEqual(config.summary_models, ["openai/gpt-4o"])

    def test_runtime_mutation_validation(self):
        """Direct validation trigger must raise ConfigValidationError if fields are mutated to invalid values at runtime."""
        config = AgentConfig()
        config.temperature = 9.9
        with self.assertRaises(ConfigValidationError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
