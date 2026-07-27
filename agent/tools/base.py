"""
Abstract Tool interface and schema generators.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

class ToolError(Exception):
    """Exception raised during tool execution failure."""
    pass



class BaseTool(ABC):
    """Abstract base class for tools used by the NERO agent."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used by LLM function calling."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description explaining purpose to LLM."""
        pass

    @property
    @abstractmethod
    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema for tool parameters."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Executes the tool logic and returns string result."""
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """Converts tool definition to OpenAI function call schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
