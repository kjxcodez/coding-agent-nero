"""
Rich CLI Logger providing subtle, progress updates and clean output.
"""

from datetime import datetime
from typing import Any, Dict

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
    """Rich terminal logger for subtle progress steps, tool calls, and reports."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.console = Console(theme=custom_theme)

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

    def info(self, message: str) -> None:
        if self.verbose:
            self.console.print(f"[dim cyan][{self._timestamp()}][/dim cyan] [bold blue][i][/bold blue] {message}")

    def progress(self, step_text: str) -> None:
        """Clean, unobtrusive progress indicator (no artificial PHASE banners)."""
        self.console.print(f"[bold bright_blue]●[/bold bright_blue] [bold bright_white]{step_text}[/bold bright_white]")

    def phase(self, phase_name: str) -> None:
        """Fallback progress call mapping to clean progress indicator."""
        self.progress(phase_name)

    def tool(self, tool_name: str, args: Dict[str, Any], result_summary: str) -> None:
        if self.verbose:
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            if len(arg_str) > 80:
                arg_str = arg_str[:77] + "..."
            self.console.print(
                f"  [bold yellow]-> TOOL [{tool_name}][/bold yellow] ([dim]{arg_str}[/dim]) "
                f"-> [dim white]{result_summary}[/dim white]"
            )

    def success(self, message: str) -> None:
        self.console.print(f"[bold green][+] SUCCESS:[/bold green] {message}")

    def warning(self, message: str) -> None:
        self.console.print(f"[bold yellow][!] WARNING:[/bold yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(Panel(f"[bold red]{message}[/bold red]", title="[bold red]Error[/bold red]", border_style="red"))

    def markdown(self, md_text: str) -> None:
        md = Markdown(md_text)
        self.console.print(md)

    def status(self, message: str):
        """Returns a Rich status spinner context manager."""
        return self.console.status(f"[bold green]{message}[/bold green]", spinner="dots")
