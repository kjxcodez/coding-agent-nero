"""
Concrete LLM provider adapters for OpenAI, OpenRouter, Google Gemini, and Anthropic.
"""

import json
from typing import Any, Dict, List, Optional
from openai import OpenAI
import anthropic

from .base import LLMProvider, LLMResponse, ToolCall
from ..config import (
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_SITE_URL,
    OPENROUTER_APP_NAME,
    GEMINI_API_KEY,
    ANTHROPIC_API_KEY,
)

def _stream_openai_compatible(client: OpenAI, kwargs: Dict[str, Any], model: str) -> LLMResponse:
    """Helper to stream OpenAI-compatible completions (OpenAI, OpenRouter, Google Gemini) and display them in the terminal."""
    from rich.console import Console, Group
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.panel import Panel
    from rich.live import Live

    console = Console()

    status = console.status("[bold cyan]NERO thinking...", spinner="dots")
    status.start()

    kwargs["stream"] = True
    response_stream = client.chat.completions.create(**kwargs)

    content_accum = ""
    reasoning_accum = ""
    tool_calls_accum = {}

    in_think_block = False
    is_first_chunk = True
    live = None

    try:
        for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if is_first_chunk:
                is_first_chunk = False
                status.stop()
                status = None

            # 1. Accumulate tool calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_accum:
                        tool_calls_accum[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_accum[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_accum[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_accum[idx]["arguments"] += tc.function.arguments

            # 2. Accumulate reasoning / thinking
            has_reasoning = False
            reasoning_chunk = ""

            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_chunk = delta.reasoning_content
                has_reasoning = True
            
            content_chunk = ""
            if hasattr(delta, "content") and delta.content:
                content_chunk = delta.content

            # Parse <think> tags if present in content_chunk
            if content_chunk:
                if "<think>" in content_chunk:
                    in_think_block = True
                    parts = content_chunk.split("<think>", 1)
                    content_accum += parts[0]
                    if len(parts) > 1:
                        if "</think>" in parts[1]:
                            in_think_block = False
                            subparts = parts[1].split("</think>", 1)
                            reasoning_accum += subparts[0]
                            content_accum += subparts[1]
                        else:
                            reasoning_accum += parts[1]
                elif "</think>" in content_chunk:
                    in_think_block = False
                    parts = content_chunk.split("</think>", 1)
                    reasoning_accum += parts[0]
                    if len(parts) > 1:
                        content_accum += parts[1]
                else:
                    if in_think_block:
                        reasoning_accum += content_chunk
                    else:
                        content_accum += content_chunk
            elif reasoning_chunk:
                reasoning_accum += reasoning_chunk

            # 3. Stream output to console if we have content or reasoning
            if (content_accum or reasoning_accum) and not tool_calls_accum:
                if live is None:
                    live = Live(console=console, auto_refresh=False)
                    live.start()

                group_elements = []
                if reasoning_accum:
                    group_elements.append(
                        Panel(
                            Text(reasoning_accum.strip(), style="dim italic"),
                            title="[bold cyan]Thinking Process[/bold cyan]",
                            border_style="cyan",
                            expand=False,
                        )
                    )
                if content_accum:
                    group_elements.append(Markdown(content_accum))

                live.update(Group(*group_elements), refresh=True)

    finally:
        if status:
            status.stop()
        if live:
            live.stop()
            console.print()

    # Build final ToolCall objects
    tool_calls: List[ToolCall] = []
    for idx in sorted(tool_calls_accum.keys()):
        tc_data = tool_calls_accum[idx]
        try:
            args = json.loads(tc_data["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(
            ToolCall(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=args,
            )
        )

    return LLMResponse(
        content=content_accum if content_accum else None,
        tool_calls=tool_calls,
        model_used=model,
        raw_response=None,
        streamed=True,
    )


class OpenAIProvider(LLMProvider):
    """Direct adapter for native OpenAI API endpoint."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or OPENAI_API_KEY
        if not key:
            raise ValueError("OPENAI_API_KEY is not set. Setup credentials via onboarding or environment.")
        self.client = OpenAI(api_key=key)

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        if stream:
            return _stream_openai_compatible(self.client, kwargs, model)

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=response,
        )


class OpenRouterProvider(LLMProvider):
    """Adapter for OpenRouter API."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or OPENROUTER_API_KEY
        if not key:
            raise ValueError("OPENROUTER_API_KEY is not set. Setup credentials via onboarding or environment.")
        self.client = OpenAI(
            api_key=key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": OPENROUTER_SITE_URL,
                "X-Title": OPENROUTER_APP_NAME,
            },
        )

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        if stream:
            return _stream_openai_compatible(self.client, kwargs, model)

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=response,
        )


class GeminiProvider(LLMProvider):
    """Direct adapter for Google Gemini API via OpenAI compatibility endpoint."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("GEMINI_API_KEY is not set. Setup credentials via onboarding or environment.")
        self.client = OpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Strip provider prefixes if any
        clean_model = model.split("/")[-1] if "/" in model else model

        # Gemini supports models like 'gemini-2.5-flash', etc.
        kwargs: Dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        if stream:
            return _stream_openai_compatible(self.client, kwargs, model)

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=response,
        )


class AnthropicProvider(LLMProvider):
    """Direct adapter for Anthropic Claude API."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or ANTHROPIC_API_KEY
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not set. Setup credentials via onboarding or environment.")
        self.client = anthropic.Anthropic(api_key=key)

    def _convert_tools(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}})
                })
        return anthropic_tools

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Strip provider prefixes
        clean_model = model.split("/")[-1] if "/" in model else model

        # Extract system prompt and convert messages
        system_prompts = []
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompts.append(msg["content"])
            else:
                role = msg["role"]
                content = msg["content"]
                
                if role == "tool":
                    anthropic_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": content
                        }]
                    })
                elif "tool_calls" in msg and msg["tool_calls"]:
                    blocks = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    for tc in msg["tool_calls"]:
                        args = tc["function"]["arguments"]
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": args
                        })
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": blocks
                    })
                else:
                    anthropic_messages.append({
                        "role": role,
                        "content": content
                    })

        system_str = "\n\n".join(system_prompts) if system_prompts else None
        
        # Format tools if provided
        anth_tools = self._convert_tools(tools) if tools else None

        kwargs: Dict[str, Any] = {
            "model": clean_model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": 4096
        }
        if system_str:
            kwargs["system"] = system_str
        if anth_tools:
            kwargs["tools"] = anth_tools

        if stream:
            return self._stream_anthropic(kwargs, model)

        response = self.client.messages.create(**kwargs)
        
        # Parse content and tool calls
        content_text = ""
        tool_calls: List[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input
                    )
                )

        return LLMResponse(
            content=content_text if content_text else None,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=response,
        )

    def _stream_anthropic(self, kwargs: Dict[str, Any], model: str) -> LLMResponse:
        """Helper to stream Anthropic messages and display them in the terminal."""
        from rich.console import Console, Group
        from rich.markdown import Markdown
        from rich.live import Live

        console = Console()

        status = console.status("[bold cyan]NERO thinking...", spinner="dots")
        status.start()

        content_accum = ""
        tool_calls_accum = {}

        is_first_chunk = True
        live = None

        try:
            with self.client.messages.stream(**kwargs) as stream:
                for event in stream:
                    # Stop status spinner on first event
                    if is_first_chunk:
                        is_first_chunk = False
                        status.stop()
                        status = None

                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_calls_accum[block.id] = {
                                "id": block.id,
                                "name": block.name,
                                "arguments": ""
                            }
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            content_accum += delta.text
                            
                            # Stream to console
                            if live is None:
                                live = Live(console=console, auto_refresh=False)
                                live.start()
                            live.update(Markdown(content_accum), refresh=True)
                        elif delta.type == "input_json_delta":
                            # Accumulate input arguments for tool use
                            # We can find the active tool use in tool_calls_accum
                            for tc_id in tool_calls_accum:
                                # We add to arguments of all currently active tool uses (typically only one)
                                tool_calls_accum[tc_id]["arguments"] += delta.partial_json
        finally:
            if status:
                status.stop()
            if live:
                live.stop()
                console.print()

        # Build final ToolCall objects
        tool_calls: List[ToolCall] = []
        for tc_id, tc_data in tool_calls_accum.items():
            try:
                args = json.loads(tc_data["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=args
                )
            )

        return LLMResponse(
            content=content_accum if content_accum else None,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=None,
            streamed=True
        )
