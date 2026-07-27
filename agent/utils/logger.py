"""
Rich CLI Logger providing subtle progress updates, clean terminal output,
and structured session-based JSONL file logging under ~/.nero/logs/.
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, Optional
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.theme import Theme

custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "success": "bold green",
    "progress": "bold bright_blue",
    "tool": "bold yellow",
})


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
        self.log_event("session_started", {
            "session_id": self.session_id,
            "os": os.name,
            "time": datetime.now().isoformat()
        })

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
        event = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            **data
        }
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            # Silent fallback if write fails to avoid interrupting agent execution
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
        self.log_event("tool_executed", {
            "tool": tool_name,
            "arguments": args,
            "summary": result_summary
        })
        if self.verbose:
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            if len(arg_str) > 80:
                arg_str = arg_str[:77] + "..."
            self.console.print(
                f"  [bold yellow]-> TOOL [{tool_name}][/bold yellow] ([dim]{arg_str}[/dim]) "
                f"-> [dim white]{result_summary}[/dim white]"
            )

    def success(self, message: str) -> None:
        self.log_event("success", {"message": message})
        self.console.print(f"[bold green][+] SUCCESS:[/bold green] {message}")

    def warning(self, message: str) -> None:
        self.log_event("warning", {"message": message})
        self.console.print(f"[bold yellow][!] WARNING:[/bold yellow] {message}")

    def error(self, message: str) -> None:
        self.log_event("error", {"message": message})
        self.console.print(Panel(f"[bold red]{message}[/bold red]", title="[bold red]Error[/bold red]", border_style="red"))

    def markdown(self, md_text: str) -> None:
        self.log_event("markdown_output", {"content": md_text})
        md = Markdown(md_text)
        self.console.print(md)

    def status(self, message: str):
        """Returns a Rich status spinner context manager."""
        self.log_event("status_spinner", {"message": message})
        return self.console.status(f"[bold green]{message}[/bold green]", spinner="dots")
