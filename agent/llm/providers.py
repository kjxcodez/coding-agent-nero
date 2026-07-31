"""
Concrete LLM provider adapters for OpenAI, OpenRouter, Google Gemini, and Anthropic.
"""

import json
import time
from typing import Any, Dict, List, Optional

import anthropic
from openai import OpenAI

from ..config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    OPENROUTER_APP_NAME,
    OPENROUTER_BASE_URL,
    OPENROUTER_SITE_URL,
)
from .base import LLMProvider, LLMResponse, ToolCall


def _stream_openai_compatible(client: OpenAI, kwargs: Dict[str, Any], model: str) -> LLMResponse:
    """Helper to stream OpenAI-compatible completions (OpenAI, OpenRouter, Google Gemini) and display them in the terminal."""
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text

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
            choices = getattr(chunk, "choices", None)
            if not choices or not isinstance(choices, (list, tuple)):
                continue
            delta = choices[0].delta

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
                        if hasattr(tc.function, "thought_signature") and getattr(tc.function, "thought_signature"):
                            tool_calls_accum[idx]["thought_signature"] = getattr(tc.function, "thought_signature")
                    if hasattr(tc, "thought_signature") and getattr(tc, "thought_signature"):
                        tool_calls_accum[idx]["thought_signature"] = getattr(tc, "thought_signature")

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

    # Build final ToolCall objects and assistant_message dict
    tool_calls: List[ToolCall] = []
    tool_calls_list = []
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

        func_dict = {
            "name": tc_data["name"],
            "arguments": tc_data["arguments"],
        }
        if "thought_signature" in tc_data:
            func_dict["thought_signature"] = tc_data["thought_signature"]
        tc_item = {"id": tc_data["id"], "type": "function", "function": func_dict}
        if "thought_signature" in tc_data:
            tc_item["thought_signature"] = tc_data["thought_signature"]
        tool_calls_list.append(tc_item)

    assistant_msg = {"role": "assistant", "content": content_accum if content_accum else None}
    if tool_calls_list:
        assistant_msg["tool_calls"] = tool_calls_list

    return LLMResponse(
        content=content_accum if content_accum else None,
        tool_calls=tool_calls,
        model_used=model,
        raw_response=None,
        streamed=True,
        assistant_message=assistant_msg,
    )


def merge_system_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Helper to merge multiple system messages into a single system message at index 0."""
    system_contents = []
    other_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_contents.append(msg["content"])
        else:
            other_messages.append(msg)
    if system_contents:
        return [{"role": "system", "content": "\n\n".join(system_contents)}] + other_messages
    return other_messages


def format_tool_messages_as_text(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts past assistant tool_calls and tool responses into plain-text assistant/user messages
    to ensure full compatibility with models/providers (like OpenRouter free models) that do
    not support structured tool call history.
    """
    new_messages = []
    for msg in messages:
        m = dict(msg)
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls_text = []
            for tc in m["tool_calls"]:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    name = func.get("name")
                    args = func.get("arguments")
                else:
                    func = getattr(tc, "function", None)
                    name = getattr(func, "name", None) if func else None
                    args = getattr(func, "arguments", None) if func else None
                calls_text.append(f"Tool Call: {name}({args})")

            content = m.get("content") or ""
            if content:
                content += "\n\n"
            content += "\n".join(calls_text)
            new_messages.append({"role": "assistant", "content": content})
        elif role == "tool":
            tool_name = m.get("name")
            tool_content = m.get("content")
            new_messages.append({"role": "user", "content": f"Tool '{tool_name}' returned:\n{tool_content}"})
        else:
            new_messages.append(m)
    return new_messages


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
        merged_messages = merge_system_messages(messages)
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": merged_messages,
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
            assistant_message=msg.model_dump(exclude_none=True),
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
        # Strip the "openrouter/" routing prefix for provider-scoped models
        # e.g. "openrouter/poolside/laguna-s-2.1:free" → "poolside/laguna-s-2.1:free"
        # BUT keep special OpenRouter router IDs as-is:
        # e.g. "openrouter/free", "openrouter/auto" → sent unchanged to the API
        suffix = model[len("openrouter/") :] if model.startswith("openrouter/") else model
        clean_model = suffix if "/" in suffix else model
        formatted_messages = format_tool_messages_as_text(messages)
        merged_messages = merge_system_messages(formatted_messages)
        kwargs: Dict[str, Any] = {
            "model": clean_model,
            "messages": merged_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        if stream:
            return _stream_openai_compatible(self.client, kwargs, clean_model)

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
            assistant_message=msg.model_dump(exclude_none=True),
        )


import urllib.error
import urllib.request


def convert_to_gemini_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively converts OpenAI schema types to Gemini native uppercase types."""
    res: Dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            res[k] = v.upper()
        elif isinstance(v, dict):
            res[k] = convert_to_gemini_schema(v)
        elif isinstance(v, list):
            res[k] = [convert_to_gemini_schema(item) if isinstance(item, dict) else item for item in v]
        else:
            res[k] = v
    return res


class GeminiProvider(LLMProvider):
    """Direct adapter for Google Gemini API via native REST and OpenAI compatibility endpoint."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set. Setup credentials via onboarding or environment.")
        self.client = OpenAI(api_key=self.api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")

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

        if tools:
            # 1. Convert messages to Gemini native format
            gemini_contents = []
            system_parts = []
            for msg in messages:
                if msg["role"] == "system":
                    if msg.get("content"):
                        system_parts.append(msg["content"])
                    continue

                if "gemini_native_content" in msg:
                    native_content = msg["gemini_native_content"]
                    if native_content and native_content.get("parts"):
                        gemini_contents.append(native_content)
                    continue

                role = "user" if msg["role"] in ("user", "tool") else "model"
                parts = []

                if msg["role"] == "assistant":
                    if msg.get("content"):
                        parts.append({"text": msg["content"]})
                    if "tool_calls" in msg and msg["tool_calls"]:
                        for tc in msg["tool_calls"]:
                            if "functionCall" in tc:
                                parts.append({"functionCall": tc["functionCall"]})
                            elif "function" in tc:
                                func_name = tc["function"]["name"]
                                args = tc["function"]["arguments"]
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except Exception:
                                        args = {}
                                func_call = {"name": func_name, "args": args}
                                if "thought_signature" in tc:
                                    func_call["thought_signature"] = tc["thought_signature"]
                                elif "thought_signature" in tc["function"]:
                                    func_call["thought_signature"] = tc["function"]["thought_signature"]
                                parts.append({"functionCall": func_call})
                elif msg["role"] == "tool":
                    tool_name = None
                    for prev in messages:
                        if prev.get("role") == "assistant" and "tool_calls" in prev:
                            for tc in prev["tool_calls"]:
                                if tc.get("id") == msg.get("tool_call_id"):
                                    tool_name = tc["function"]["name"]
                                    break
                        if tool_name:
                            break
                    if not tool_name:
                        tool_name = msg.get("name") or "default_api:clone_repo"

                    try:
                        resp_json = json.loads(msg["content"])
                    except Exception:
                        resp_json = {"output": msg["content"]}
                    parts.append({"functionResponse": {"name": tool_name, "response": resp_json}})
                else:
                    if msg.get("content"):
                        parts.append({"text": msg["content"]})

                # Only append the message if it actually contains parts!
                if parts:
                    gemini_contents.append({"role": role, "parts": parts})

            # 2. Build REST body
            if not gemini_contents:
                gemini_contents.append({"role": "user", "parts": [{"text": "Start executing the plan."}]})
            req_body = {"contents": gemini_contents, "generationConfig": {"temperature": temperature}}
            if system_parts:
                req_body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

            declarations = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool["function"]
                    declarations.append(
                        {
                            "name": func["name"],
                            "description": func.get("description", ""),
                            "parameters": convert_to_gemini_schema(func.get("parameters", {})),
                        }
                    )
            req_body["tools"] = [{"functionDeclarations": declarations}]

            # 3. Post to REST API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={self.api_key}"
            req_data = json.dumps(req_body).encode("utf-8")

            # Retry with exponential backoff for transient 503/429 errors
            max_retries = 4
            last_error: Optional[Exception] = None
            resp_data = None
            for attempt in range(max_retries):
                req = urllib.request.Request(
                    url, data=req_data, headers={"Content-Type": "application/json"}, method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                    break  # Success — exit retry loop
                except urllib.error.HTTPError as e:
                    error_body = e.read().decode("utf-8")
                    last_error = RuntimeError(f"Gemini Native REST API Error {e.code}: {e.reason}\n{error_body}")
                    if e.code in (503, 429) and attempt < max_retries - 1:
                        wait = 2**attempt  # 1s, 2s, 4s, 8s
                        time.sleep(wait)
                        continue
                    raise last_error
            if resp_data is None:
                raise last_error or RuntimeError("Gemini REST API returned no data")

            candidate = resp_data["candidates"][0]
            content_obj = candidate["content"]
            parts = content_obj.get("parts", [])

            content_text = ""
            tool_calls = []
            for part in parts:
                if "text" in part:
                    content_text += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append(
                        ToolCall(
                            id=fc.get("thought_signature") or fc["name"],
                            name=fc["name"],
                            arguments=fc.get("args") or {},
                        )
                    )

            # Reconstruct OpenAI-compatible assistant_message
            openai_tc = []
            for part in parts:
                if "functionCall" in part:
                    fc = part["functionCall"]
                    openai_tc.append(
                        {
                            "id": fc.get("thought_signature") or fc["name"],
                            "type": "function",
                            "function": {
                                "name": fc["name"],
                                "arguments": json.dumps(fc.get("args") or {}),
                                "thought_signature": fc.get("thought_signature"),
                            },
                            "thought_signature": fc.get("thought_signature"),
                            "functionCall": fc,
                        }
                    )

            assistant_msg = {
                "role": "assistant",
                "content": content_text if content_text else None,
                "gemini_native_content": content_obj,
            }
            if openai_tc:
                assistant_msg["tool_calls"] = openai_tc

            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                model_used=model,
                raw_response=resp_data,
                assistant_message=assistant_msg,
            )
        else:
            # Use OpenAI compatibility endpoint for low-latency conversational streaming
            merged_messages = merge_system_messages(messages)
            kwargs: Dict[str, Any] = {
                "model": clean_model,
                "messages": merged_messages,
                "temperature": temperature,
            }
            if stream:
                return _stream_openai_compatible(self.client, kwargs, model)

            response = self.client.chat.completions.create(**kwargs)
            msg = response.choices[0].message

            return LLMResponse(
                content=msg.content,
                tool_calls=[],
                model_used=model,
                raw_response=response,
                assistant_message=msg.model_dump(exclude_none=True),
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
                anthropic_tools.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
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
                    anthropic_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": msg["tool_call_id"], "content": content}
                            ],
                        }
                    )
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
                        blocks.append(
                            {"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": args}
                        )
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                else:
                    anthropic_messages.append({"role": role, "content": content})

        system_str = "\n\n".join(system_prompts) if system_prompts else None

        # --- Merge consecutive same-role messages to satisfy Anthropic's strict
        # alternating role requirement. When the LLM calls multiple tools in one
        # turn, each tool result is appended as a separate "user" message in the
        # OpenAI format. The translation loop above produces one {"role": "user"}
        # per tool result. Anthropic rejects two consecutive "user" messages with
        # a 400 Bad Request. We merge them here by concatenating their content
        # lists before sending.
        merged: List[Dict[str, Any]] = []
        for msg in anthropic_messages:
            if (
                merged
                and merged[-1]["role"] == msg["role"]
                and isinstance(merged[-1]["content"], list)
                and isinstance(msg["content"], list)
            ):
                # Extend the previous message's content block list in-place.
                merged[-1]["content"].extend(msg["content"])
            else:
                # Deep-copy to avoid mutating the original list objects.
                merged.append({"role": msg["role"], "content": msg["content"]})
        anthropic_messages = merged

        # Format tools if provided
        anth_tools = self._convert_tools(tools) if tools else None

        kwargs: Dict[str, Any] = {
            "model": clean_model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": 4096,
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
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        openai_tc = []
        for tc in tool_calls:
            openai_tc.append(
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            )
        assistant_msg = {"role": "assistant", "content": content_text if content_text else None}
        if openai_tc:
            assistant_msg["tool_calls"] = openai_tc

        return LLMResponse(
            content=content_text if content_text else None,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=response,
            assistant_message=assistant_msg,
        )

    def _stream_anthropic(self, kwargs: Dict[str, Any], model: str) -> LLMResponse:
        """Helper to stream Anthropic messages and display them in the terminal."""
        from rich.console import Console
        from rich.live import Live
        from rich.markdown import Markdown

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
                            tool_calls_accum[block.id] = {"id": block.id, "name": block.name, "arguments": ""}
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

        # Build final ToolCall objects and assistant_message dict
        tool_calls: List[ToolCall] = []
        openai_tc = []
        for tc_id, tc_data in tool_calls_accum.items():
            try:
                args = json.loads(tc_data["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc_data["id"], name=tc_data["name"], arguments=args))
            openai_tc.append(
                {
                    "id": tc_data["id"],
                    "type": "function",
                    "function": {"name": tc_data["name"], "arguments": tc_data["arguments"]},
                }
            )

        assistant_msg = {"role": "assistant", "content": content_accum if content_accum else None}
        if openai_tc:
            assistant_msg["tool_calls"] = openai_tc

        return LLMResponse(
            content=content_accum if content_accum else None,
            tool_calls=tool_calls,
            model_used=model,
            raw_response=None,
            streamed=True,
            assistant_message=assistant_msg,
        )
