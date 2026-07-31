"""
Rich CLI Logger providing subtle progress updates, clean terminal output,
and structured session-based JSONL file logging under ~/.nero/logs/.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme

custom_theme = Theme(
    {
        "info": "dim cyan",
        "warning": "magenta",
        "danger": "bold red",
        "success": "bold green",
        "progress": "bold bright_blue",
        "tool": "bold yellow",
    }
)

# Tool display config: maps tool name -> (icon, label, color, content_key)
_READ_TOOLS = {"read_file", "list_files"}
_WRITE_TOOLS = {"write_file", "create_file", "replace_text"}
_SEARCH_TOOLS = {"search_code_content", "search_filenames", "search_symbols", "search_routes"}
_GIT_TOOLS = {"git_diff", "git_status"}
_RUN_TOOLS = {"run_command"}
_CLONE_TOOLS = {"clone_repo"}


def _count_diff_stats(old: str, new: str) -> str:
    """Returns a '+N -M' diff stat string between two text blobs."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    added = sum(1 for l in new_lines if l not in old_lines)
    removed = sum(1 for l in old_lines if l not in new_lines)
    parts = []
    if added:
        parts.append(f"[bold green]+{added}[/bold green]")
    if removed:
        parts.append(f"[bold red]-{removed}[/bold red]")
    return " ".join(parts) if parts else "[dim](no net changes)[/dim]"


def _collapse(text: str, max_lines: int = 4, max_chars: int = 200) -> str:
    """Returns a short preview of text, collapsing long content."""
    if not text:
        return "(empty)"
    lines = text.strip().splitlines()
    preview_lines = lines[:max_lines]
    preview = " ↵ ".join(line.strip() for line in preview_lines if line.strip())
    if len(preview) > max_chars:
        preview = preview[:max_chars] + "…"
    if len(lines) > max_lines:
        preview += f"  [dim](+{len(lines) - max_lines} more lines)[/dim]"
    return preview


class AgentLogger:
    """Rich terminal logger combined with structured session file logging."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.console = Console(theme=custom_theme)

        # Initialize session logging
        self.session_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        self.log_dir = os.path.expanduser("~/.nero/logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, f"{self.session_id}.log")

        # Log session startup
        self.log_event(
            "session_started", {"session_id": self.session_id, "os": os.name, "time": datetime.now().isoformat()}
        )

    def print_ascii_art(self) -> None:
        ascii_logo = r"""
 [bold cyan]
  ███╗   ██╗███████╗██████╗  ██████╗ 
  ████╗  ██║██╔════╝██╔══██╗██╔═══██╗
  ██╔██╗ ██║█████╗  ██████╔╝██║   ██║
  ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║
  ██║ ╚████║███████╗██║  ██║╚██████╔╝
  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ 
 [/bold cyan]
 [bold bright_white]   N E R O   —   A U T O N O M O U S   A I   C O D I N G   A G E N T   [/bold bright_white]
 [dim magenta]       Explore • Analyze • Plan • Execute • Verify • Repair • Review       [/dim magenta]
"""
        self.console.print(Panel(ascii_logo, border_style="cyan", expand=False))

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Appends a structured event into the JSONL session log file."""
        event = {"timestamp": datetime.now().isoformat(), "event": event_type, **data}
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    def info(self, message: str) -> None:
        self.log_event("info", {"message": message})
        if self.verbose:
            self.console.print(f"[dim cyan][{self._timestamp()}][/dim cyan] [bold blue][i][/bold blue] {message}")

    def progress(self, step_text: str) -> None:
        """Clean progress indicator."""
        self.log_event("progress", {"step": step_text})
        self.console.print(f"[bold bright_blue]●[/bold bright_blue] [bold bright_white]{step_text}[/bold bright_white]")

    def phase(self, phase_name: str) -> None:
        self.progress(phase_name)

    def tool(self, tool_name: str, args: Dict[str, Any], result_summary: str) -> None:
        """Renders smart, context-aware tool call output in the terminal."""
        self.log_event("tool_executed", {"tool": tool_name, "arguments": args, "summary": result_summary})
        if not self.verbose:
            return

        if tool_name in _READ_TOOLS:
            self._render_read_tool(tool_name, args, result_summary)
        elif tool_name in _WRITE_TOOLS:
            self._render_write_tool(tool_name, args, result_summary)
        elif tool_name in _SEARCH_TOOLS:
            self._render_search_tool(tool_name, args, result_summary)
        elif tool_name in _GIT_TOOLS:
            self._render_git_tool(tool_name, args, result_summary)
        elif tool_name in _RUN_TOOLS:
            self._render_run_tool(tool_name, args, result_summary)
        elif tool_name in _CLONE_TOOLS:
            self._render_clone_tool(tool_name, args, result_summary)
        else:
            self._render_generic_tool(tool_name, args, result_summary)

    def _render_read_tool(self, tool_name: str, args: Dict, result: str) -> None:
        if tool_name == "read_file":
            path = args.get("path") or args.get("file_path") or "?"
            fname = os.path.basename(path)
            preview = _collapse(result)
            self.console.print(
                f"  [bold cyan]📄 Reading[/bold cyan]  [bold]{fname}[/bold]  [dim]({path})[/dim]\n"
                f"     [dim]{preview}[/dim]"
            )
        elif tool_name == "list_files":
            path = args.get("path", ".")
            count = len(result.strip().splitlines()) if result.strip() else 0
            self.console.print(
                f"  [bold cyan]📂 Listing[/bold cyan]  [bold]{path}[/bold]  [dim]→ {count} file(s)[/dim]"
            )

    def _render_write_tool(self, tool_name: str, args: Dict, result: str) -> None:
        if tool_name == "write_file":
            path = args.get("path") or args.get("file_path") or "?"
            fname = os.path.basename(path)
            content = args.get("content", "")
            lines = content.splitlines() if content else []
            self.console.print(
                f"  [bold yellow]✏️  Writing[/bold yellow]   [bold]{fname}[/bold]  [dim]({path})[/dim]  "
                f"[bold green]+{len(lines)} lines[/bold green]"
            )
        elif tool_name == "create_file":
            path = args.get("path") or args.get("file_path") or "?"
            fname = os.path.basename(path)
            self.console.print(f"  [bold green]✨ Creating[/bold green]  [bold]{fname}[/bold]  [dim]({path})[/dim]")
        elif tool_name == "replace_text":
            path = args.get("path") or args.get("file_path") or "?"
            fname = os.path.basename(path)
            old = args.get("old_text") or args.get("old") or ""
            new = args.get("new_text") or args.get("new") or ""
            diff_stat = _count_diff_stats(old, new)
            self.console.print(
                f"  [bold yellow]✏️  Modifying[/bold yellow] [bold]{fname}[/bold]  [dim]({path})[/dim]  {diff_stat}"
            )

    def _render_search_tool(self, tool_name: str, args: Dict, result: str) -> None:
        query = args.get("query") or args.get("pattern") or args.get("name") or args.get("route") or "?"
        hits = len([l for l in result.strip().splitlines() if l.strip()]) if result.strip() else 0
        icons = {
            "search_code_content": "🔍",
            "search_filenames": "🗂️",
            "search_symbols": "🔣",
            "search_routes": "🌐",
        }
        icon = icons.get(tool_name, "🔍")
        label = tool_name.replace("search_", "").replace("_", " ").title()
        self.console.print(
            f'  [bold magenta]{icon} Search {label}[/bold magenta]  [dim]"{query}"[/dim]  [dim]→ {hits} result(s)[/dim]'
        )

    def _render_git_tool(self, tool_name: str, args: Dict, result: str) -> None:
        if tool_name == "git_diff":
            # Count +/- lines in diff output
            added = sum(1 for l in result.splitlines() if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in result.splitlines() if l.startswith("-") and not l.startswith("---"))
            stat = ""
            if added:
                stat += f" [bold green]+{added}[/bold green]"
            if removed:
                stat += f" [bold red]-{removed}[/bold red]"
            self.console.print(f"  [bold blue]⎔  Git Diff[/bold blue]{stat}")
        elif tool_name == "git_status":
            changed = len([l for l in result.splitlines() if l.strip() and not l.startswith("#")])
            self.console.print(f"  [bold blue]⎔  Git Status[/bold blue]  [dim]→ {changed} entry/entries[/dim]")

    def _render_run_tool(self, tool_name: str, args: Dict, result: str) -> None:
        cmd = args.get("command") or args.get("cmd") or "?"
        # Trim long commands
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        success = "error" not in result.lower() and "failed" not in result.lower()
        status = "[bold green]✓[/bold green]" if success else "[bold red]✗[/bold red]"
        self.console.print(f"  [bold bright_blue]⚡ Run[/bold bright_blue]  [dim]{cmd}[/dim]  {status}")

    def _render_clone_tool(self, tool_name: str, args: Dict, result: str) -> None:
        url = args.get("url_or_path") or args.get("url") or "?"
        success = "successfully" in result.lower()
        if success:
            self.console.print(
                f"  [bold green]⬇  Cloned[/bold green]  [dim]{url}[/dim]\n     [dim]{result.strip()[:100]}[/dim]"
            )
        else:
            self.console.print(
                f"  [bold red]✗  Clone failed[/bold red]  [dim]{url}[/dim]\n     [dim]{result.strip()[:100]}[/dim]"
            )

    def _render_generic_tool(self, tool_name: str, args: Dict, result: str) -> None:
        arg_str = ", ".join(f"{k}={str(v)!r}" for k, v in args.items())
        if len(arg_str) > 60:
            arg_str = arg_str[:57] + "..."
        preview = _collapse(result)
        self.console.print(
            f"  [bold yellow]⚙  {tool_name}[/bold yellow]  [dim]({arg_str})[/dim]\n     [dim]{preview}[/dim]"
        )

    def success(self, message: str) -> None:
        self.log_event("success", {"message": message})
        self.console.print(f"[bold green][+] SUCCESS:[/bold green] {message}")

    def warning(self, message: str) -> None:
        self.log_event("warning", {"message": message})
        self.console.print(f"[bold yellow][!] WARNING:[/bold yellow] {message}")

    def error(self, message: str) -> None:
        self.log_event("error", {"message": message})
        self.console.print(
            Panel(f"[bold red]{message}[/bold red]", title="[bold red]Error[/bold red]", border_style="red")
        )

    def markdown(self, md_text: str) -> None:
        self.log_event("markdown_output", {"content": md_text})
        md = Markdown(md_text)
        self.console.print(md)

    def status(self, message: str):
        """Returns a Rich status spinner context manager."""
        self.log_event("status_spinner", {"message": message})
        return self.console.status(f"[bold green]{message}[/bold green]", spinner="dots")
