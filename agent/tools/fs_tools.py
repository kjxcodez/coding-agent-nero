"""
File system tools for listing, reading, writing, creating, and replacing text with memory caching.
Optimized for performance and token usage.
"""

import os
import difflib
from datetime import datetime
from typing import Any, Dict, Optional
from .base import BaseTool, ToolError
from .safety import ToolSafetyGuard, SecurityError
from ..config import AgentConfig


class ListFilesTool(BaseTool):
    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return "List all files under a directory in the repository (recursive)."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to repo root. Defaults to '.'.",
                }
            },
        }

    def execute(self, path: str = ".", **kwargs) -> str:
        try:
            target_dir = self.safety.resolve_and_validate_path(self.repo_root, path)
            if not os.path.isdir(target_dir):
                raise ToolError(f"Directory does not exist: {path}")

            file_list = []
            for root, dirs, files in os.walk(target_dir):
                dirs[:] = [d for d in dirs if d not in self.config.ignored_dirs]
                rel_root = os.path.relpath(root, self.repo_root)
                if any(ignored in rel_root.split(os.sep) for ignored in self.config.ignored_dirs):
                    continue

                for f in files:
                    rel_file = f if rel_root == "." else os.path.join(rel_root, f)
                    file_list.append(rel_file.replace(os.sep, "/"))

            return "\n".join(sorted(file_list)) or "(empty directory)"
        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class ReadFileTool(BaseTool):
    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file in the repository, supporting line slices, binary protection, and size limits."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
                "start_line": {"type": "integer", "description": "Optional 1-indexed start line (inclusive)."},
                "end_line": {"type": "integer", "description": "Optional 1-indexed end line (inclusive)."},
            },
            "required": ["path"],
        }

    def _is_binary(self, filepath: str) -> bool:
        """Detect binary file by checking for null bytes in the first block."""
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(1024)
                return b"\0" in chunk
        except Exception:
            return False

    def execute(self, path: Optional[str] = None, start_line: Optional[int] = None, end_line: Optional[int] = None, **kwargs) -> str:
        try:
            if not path:
                path = kwargs.get("path") or kwargs.get("filepath") or kwargs.get("file")
            if not path:
                raise ToolError("Missing required argument: 'path'")
            target_file = self.safety.resolve_and_validate_path(self.repo_root, path)
            if not os.path.isfile(target_file):
                raise ToolError(f"File does not exist: {path}")

            # Binary protection
            if self._is_binary(target_file):
                raise ToolError(f"Cannot read binary file: {path}")

            size = os.path.getsize(target_file)
            
            # If no line range specified, check if full size exceeds limit
            if start_line is None and end_line is None:
                if size > self.config.max_read_bytes:
                    raise ToolError(
                        f"File too large ({size} bytes > {self.config.max_read_bytes} max). "
                        "Specify start_line and end_line to read a partial slice."
                    )
                with open(target_file, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                
                if self.memory:
                    self.memory.cache_file(path, content)
                return content
            
            # Optimized partial read: read only requested lines
            lines = []
            current_line = 1
            s = start_line if (start_line and start_line > 0) else 1
            e = end_line if (end_line and end_line >= s) else None
            
            with open(target_file, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if current_line >= s:
                        if e is not None and current_line > e:
                            break
                        lines.append(line)
                    current_line += 1
            
            return "".join(lines)

        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class WriteFileTool(BaseTool):
    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write full file contents into target path."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
                "content": {"type": "string", "description": "Full new contents of the file."},
            },
            "required": ["path", "content"],
        }

    def execute(self, path: Optional[str] = None, content: Optional[str] = None, **kwargs) -> str:
        try:
            if not path:
                path = kwargs.get("path") or kwargs.get("filepath") or kwargs.get("file")
            if content is None:
                content = kwargs.get("content") or kwargs.get("contents") or kwargs.get("text")
            
            if not path:
                raise ToolError("Missing required argument: 'path'")
            if content is None:
                raise ToolError("Missing required argument: 'content'")
                
            target_file = self.safety.resolve_and_validate_path(self.repo_root, path)
            prev_content = ""
            if os.path.isfile(target_file):
                with open(target_file, "r", encoding="utf-8", errors="replace") as fh:
                    prev_content = fh.read()

            if self.memory and getattr(self.memory, "in_repair_loop", False):
                basename = os.path.basename(path)
                if basename == "package.json":
                    try:
                        import json
                        orig_json = json.loads(prev_content) if prev_content else {}
                        upd_json = json.loads(content)
                        orig_test = orig_json.get("scripts", {}).get("test")
                        upd_test = upd_json.get("scripts", {}).get("test")
                        if orig_test != upd_test:
                            raise ToolError("Modifying verification test scripts in package.json during the repair loop is strictly prohibited.")
                    except Exception as e:
                        if "prohibited" in str(e):
                            raise ToolError(str(e))
                        if "test" in content or "scripts" in content:
                            raise ToolError("Modifying verification test scripts in package.json during the repair loop is strictly prohibited.")

            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as fh:
                fh.write(content)

            if self.memory:
                self.memory.record_edit(path, prev_content, datetime.now().isoformat(), new_content=content)
                self.memory.cache_file(path, content)

            return f"Successfully wrote {len(content)} bytes to '{path}'."
        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class CreateFileTool(BaseTool):
    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "create_file"

    @property
    def description(self) -> str:
        return "Create a new file in repository if it does not already exist."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
                "content": {"type": "string", "description": "Content of the new file."},
            },
            "required": ["path", "content"],
        }

    def execute(self, path: Optional[str] = None, content: Optional[str] = None, **kwargs) -> str:
        try:
            if not path:
                path = kwargs.get("path") or kwargs.get("filepath") or kwargs.get("file")
            if content is None:
                content = kwargs.get("content") or kwargs.get("contents") or kwargs.get("text") or ""
            
            if not path:
                raise ToolError("Missing required argument: 'path'")
                
            target_file = self.safety.resolve_and_validate_path(self.repo_root, path)
            if os.path.exists(target_file):
                raise ToolError(f"File already exists at '{path}'. Use write_file to overwrite.")
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as fh:
                fh.write(content)

            if self.memory:
                self.memory.record_edit(path, "", datetime.now().isoformat(), new_content=content)
                self.memory.cache_file(path, content)

            return f"Successfully created new file '{path}' ({len(content)} bytes)."
        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"


class ReplaceTextTool(BaseTool):
    def __init__(self, config: AgentConfig, safety: ToolSafetyGuard, repo_root: str, memory: Optional[Any] = None):
        self.config = config
        self.safety = safety
        self.repo_root = os.path.abspath(repo_root)
        self.memory = memory

    @property
    def name(self) -> str:
        return "replace_text"

    @property
    def description(self) -> str:
        return "Replace exact occurrences of target text with new replacement text in a file (targeted edit)."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
                "old_text": {"type": "string", "description": "Exact text substring to replace."},
                "new_text": {"type": "string", "description": "Replacement text string."},
            },
            "required": ["path", "old_text", "new_text"],
        }

    def execute(self, path: Optional[str] = None, old_text: Optional[str] = None, new_text: Optional[str] = None, **kwargs) -> str:
        try:
            if not path:
                path = kwargs.get("path") or kwargs.get("filepath") or kwargs.get("file")
            if old_text is None:
                old_text = kwargs.get("old_text") or kwargs.get("old") or kwargs.get("replace") or kwargs.get("target")
            if new_text is None:
                new_text = kwargs.get("new_text") or kwargs.get("new") or kwargs.get("with") or kwargs.get("replacement")
                
            if not path:
                raise ToolError("Missing required argument: 'path'")
            if old_text is None:
                raise ToolError("Missing required argument: 'old_text'")
            if new_text is None:
                raise ToolError("Missing required argument: 'new_text'")
                
            target_file = self.safety.resolve_and_validate_path(self.repo_root, path)
            if not os.path.isfile(target_file):
                raise ToolError(f"File does not exist: {path}")

            with open(target_file, "r", encoding="utf-8", errors="replace") as fh:
                original = fh.read()

            if old_text not in original:
                raise ToolError(f"Target 'old_text' was not found in '{path}'. Make sure spacing matches exactly.")

            count = original.count(old_text)
            updated = original.replace(old_text, new_text)

            if self.memory and getattr(self.memory, "in_repair_loop", False):
                basename = os.path.basename(path)
                if basename == "package.json":
                    try:
                        import json
                        orig_json = json.loads(original)
                        upd_json = json.loads(updated)
                        orig_test = orig_json.get("scripts", {}).get("test")
                        upd_test = upd_json.get("scripts", {}).get("test")
                        if orig_test != upd_test:
                            raise ToolError("Modifying verification test scripts in package.json during the repair loop is strictly prohibited.")
                    except Exception as e:
                        if "prohibited" in str(e):
                            raise ToolError(str(e))
                        if "test" in new_text or "scripts" in new_text:
                            raise ToolError("Modifying verification test scripts in package.json during the repair loop is strictly prohibited.")

            with open(target_file, "w", encoding="utf-8") as fh:
                fh.write(updated)

            # Generate and return a unified diff snippet for direct verification feedback
            diff_lines = difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm=""
            )
            diff_snippet = "\n".join(list(diff_lines)[:15]) # cap output diff preview

            if self.memory:
                self.memory.record_edit(path, original, datetime.now().isoformat(), new_content=updated)
                self.memory.cache_file(path, updated)

            return (
                f"Successfully replaced {count} occurrence(s) of target text in '{path}'.\n"
                f"Diff preview:\n```diff\n{diff_snippet}\n```"
            )
        except (SecurityError, ToolError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:
            return f"ERROR (unexpected): {exc}"