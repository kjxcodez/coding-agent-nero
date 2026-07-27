"""
NERO Autonomous AI Coding Agent CLI - Interactive REPL & Command Engine.
"""

import sys, os
import typer

from typing import Optional

from rich.console import Console
from rich.panel import Panel


from .utils.logger import AgentLogger

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



def start_repl_session():
    """Starts interactive REPL session with stateful WorkingMemory."""
    logger = AgentLogger(verbose=True)
    logger.print_ascii_art()
    logger.info("Starting NERO REPL session...")


    console.print(Panel(
        f"[dim]Type your prompt (e.g. 'Add tags to notes' or 'Explain how notes route works'), type [bold green]/help[/bold green] for commands.[/dim]",
        border_style="cyan",
    ))



@app.command()
def run():
    """
    Run the NERO Autonomous AI Coding Agent CLI.
    """
    show_help_panel()
    # Here you can add the logic to start the REPL or command engine.
    start_repl_session()


if __name__ == "__main__":
    app()
