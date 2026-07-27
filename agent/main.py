"""
NERO Autonomous AI Coding Agent CLI - Interactive REPL & Command Engine.
"""

import sys, os
import typer

from typing import Optional

from rich.console import Console
from rich.panel import Panel

app = typer.Typer(
    name="nero",
    help="NERO Autonomous AI Coding Agent CLI - Interactive REPL & Command Engine.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()


def show_help_panel():
    help_text = """
    [bold cyan]NERO Autonomous AI Coding Agent CLI[/bold cyan]
    """
    console.print(Panel(help_text, title="NERO CLI Help", expand=False))


@app.command()
def run():
    """
    Run the NERO Autonomous AI Coding Agent CLI.
    """
    show_help_panel()
    # Here you can add the logic to start the REPL or command engine.


if __name__ == "__main__":
    app()
