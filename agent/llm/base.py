"""
Abstract LLM Provider interface and response structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """Standardized representation of an LLM tool call."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Standardized LLM completion response."""
    content: Optional[str]
    tool_calls: List[ToolCall] = field(default_factory=list)
    model_used: str = "unknown"
    raw_response: Any = None
    streamed: bool = False
    assistant_message: Optional[Dict[str, Any]] = None


class LLMProvider(ABC):
    """Abstract base class for all LLM service providers."""

    @abstractmethod
    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Generates completion using specified model and messages."""
        pass
