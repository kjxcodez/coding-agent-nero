"""
NERO Autonomous AI Coding Agent CLI — Interactive REPL & Command Engine.
"""

import sys
import os
import json
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# Force UTF-8 on Windows standard streams to avoid UnicodeEncodeError in legacy consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from .config import AgentConfig
from .context import WorkingMemory
from .memory import SessionMemory
from .agent_core import AgentCore
from .utils.logger import AgentLogger

app = typer.Typer(
    name="nero",
    help="NERO Autonomous AI Coding Agent CLI — Interactive REPL & Command Engine.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

DEFAULT_REPO_URL = "https://github.com/callicoder/node-easy-notes-app"
DEFAULT_REQUEST = "Improve the application so users can better organise and search their notes."


def build_config(
    model: Optional[str] = None,
    planner_models: Optional[str] = None,
    coder_models: Optional[str] = None,
    verifier_models: Optional[str] = None,
    reviewer_models: Optional[str] = None,
    summary_models: Optional[str] = None,
    max_iterations: int = 15,
    max_repair_attempts: int = 3,
    dest: str = "./target_repo",
) -> AgentConfig:
    if model:
        config = AgentConfig.with_single_model(model)
    else:
        config = AgentConfig()
        if planner_models:
            config.planner_models = [m.strip() for m in planner_models.split(",")]
        if coder_models:
            config.coder_models = [m.strip() for m in coder_models.split(",")]
        if verifier_models:
            config.verifier_models = [m.strip() for m in verifier_models.split(",")]
        if reviewer_models:
            config.reviewer_models = [m.strip() for m in reviewer_models.split(",")]
        if summary_models:
            config.summary_models = [m.strip() for m in summary_models.split(",")]

    config.max_iterations = max_iterations
    config.max_repair_attempts = max_repair_attempts
    config.repo_path = dest
    return config


def show_help_panel():
    help_text = (
        "[bold yellow]NERO REPL Commands:[/bold yellow]\n\n"
        "  • [bold green]<any prompt>[/bold green]          Natural language: ask questions, clone repos, request edits.\n"
        "  • [bold green]/repo <path_or_url>[/bold green]  Switch active workspace repository.\n"
        "  • [bold green]/context[/bold green]             Print full repository intelligence map.\n"
        "  • [bold green]/architecture[/bold green]         Show detailed architecture report (components, layers, env vars).\n"
        "  • [bold green]/routes[/bold green]              Show detected API routes in the repository.\n"
        "  • [bold green]/symbols <name>[/bold green]      Look up a symbol definition in the index.\n"
        "  • [bold green]/memory[/bold green]              Show full session memory and edit log.\n"
        "  • [bold green]/plan[/bold green]                Show the current modification plan and step statuses.\n"
        "  • [bold green]/resume[/bold green]              Resume an interrupted modification task.\n"
        "  • [bold green]/diff[/bold green]                Show active git diff.\n"
        "  • [bold green]/undo[/bold green]                Revert recent uncommitted changes.\n"
        "  • [bold green]/status[/bold green]              Display session working memory status.\n"
        "  • [bold green]/logs [view|list][/bold green]       View current session log file or list recent sessions.\n"
        "  • [bold green]/model [name][/bold green]         Show or switch active role-based models.\n"
        "  • [bold green]/auto[/bold green]                Run default autonomous benchmark task.\n"
        "  • [bold green]/help[/bold green]                Show this help panel.\n"
        "  • [bold green]exit[/bold green] or [bold green]quit[/bold green]          Exit NERO session.\n"
    )
    console.print(Panel(help_text, title="[bold cyan]NERO Help[/bold cyan]", border_style="cyan"))


def start_repl_session(
    initial_request: Optional[str] = None,
    initial_repo: str = DEFAULT_REPO_URL,
    initial_dest: str = "./target_repo",
    config: Optional[AgentConfig] = None,
):
    """Starts interactive REPL session with stateful WorkingMemory."""
    # Ensure onboarding runs first
    from .onboarding import run_onboarding_if_needed
    run_onboarding_if_needed()

    logger = AgentLogger(verbose=True)
    logger.print_ascii_art()

    current_config = config or build_config(dest=initial_dest)
    memory = WorkingMemory(repo_path=initial_dest)
    agent = AgentCore(current_config, memory, logger)

    console.print(Panel(
        f"[bold yellow]Target Workspace:[/bold yellow] [bold green]{initial_dest}[/bold green]\n"
        f"[dim]Type your prompt (e.g. 'Add tags to notes' or 'Explain how notes route works'), type [bold green]/help[/bold green] for commands.[/dim]",
        border_style="cyan",
    ))

    if initial_request:
        console.print(f"\n[bold green]NERO: Executing prompt: '{initial_request}'[/bold green]\n")
        try:
            agent.process_prompt(initial_request)
        except Exception as exc:
            logger.error(f"Error processing prompt: {exc}")

    while True:
        try:
            repo_name = os.path.basename(os.path.abspath(current_config.repo_path))
            prompt_str = f"[bold cyan]nero [{repo_name}]>[/bold cyan]"
            
            user_input = Prompt.ask(prompt_str).strip()

            if not user_input:
                continue

            # Handle Slash Commands
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd in ["/exit", "/quit", "/q"]:
                    console.print("[dim]Goodbye from NERO![/dim]")
                    break

                if cmd in ["/help", "/h", "/?"]:
                    show_help_panel()
                    continue

                if cmd in ["/status", "/s"]:
                    agent._handle_status_query()
                    continue

                if cmd in ["/diff", "/d"]:
                    agent._handle_diff_query()
                    continue

                if cmd in ["/undo", "/u"]:
                    agent._handle_undo()
                    continue

                if cmd == "/auto":
                    console.print("\n[bold green]NERO: Running default autonomous task...[/bold green]\n")
                    try:
                        agent.process_prompt(DEFAULT_REQUEST)
                    except KeyboardInterrupt:
                        console.print("\n[bold yellow]Task execution cancelled by user.[/bold yellow]\n")
                    continue

                if cmd in ["/context", "/ctx"]:
                    agent._handle_context_query()
                    continue

                if cmd == "/routes":
                    agent._handle_routes_query()
                    continue

                if cmd in ("/architecture", "/arch"):
                    agent._handle_architecture_query()
                    continue

                if cmd in ("/resume",):
                    agent._handle_resume()
                    continue

                if cmd in ("/memory", "/mem"):
                    agent._handle_memory_query()
                    continue

                if cmd in ("/plan",):
                    agent._handle_plan_query()
                    continue

                if cmd in ["/logs", "/log"]:
                    log_file = logger.log_file
                    log_dir = logger.log_dir
                    if not arg or arg.lower() in ("view", "cat", "show"):
                        if not os.path.isfile(log_file):
                            console.print("[yellow]No log file found for this session.[/yellow]")
                        else:
                            console.print(f"[bold cyan]Showing logs for current session: {log_file}[/bold cyan]")
                            try:
                                with open(log_file, "r", encoding="utf-8") as f:
                                    for line in f:
                                        if not line.strip():
                                            continue
                                        event = json.loads(line)
                                        ts = event.get("timestamp", "").split("T")[-1][:8]
                                        evt_type = event.get("event", "info")
                                        if evt_type == "tool_executed":
                                            console.print(f"[dim]{ts}[/dim] [bold yellow]TOOL[/bold yellow] [cyan]{event.get('tool')}[/cyan]({event.get('arguments')}) -> {event.get('summary')}")
                                        elif evt_type == "progress":
                                            console.print(f"[dim]{ts}[/dim] [bold bright_blue]PROGRESS[/bold bright_blue] {event.get('step')}")
                                        elif evt_type == "error":
                                            console.print(f"[dim]{ts}[/dim] [bold red]ERROR[/bold red] {event.get('message')}")
                                        elif evt_type == "success":
                                            console.print(f"[dim]{ts}[/dim] [bold green]SUCCESS[/bold green] {event.get('message')}")
                                        else:
                                            msg = event.get("message") or event.get("content") or str(event)
                                            console.print(f"[dim]{ts}[/dim] [bold cyan]{evt_type.upper()}[/bold cyan] {msg}")
                            except Exception as exc:
                                console.print(f"[bold red]Failed to read log file: {exc}[/bold red]")
                    elif arg.lower() == "list":
                        console.print(f"[bold cyan]Logs directory: {log_dir}[/bold cyan]")
                        try:
                            files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True)
                            if not files:
                                console.print("[yellow]No log files found.[/yellow]")
                            else:
                                for f in files[:10]:
                                    fpath = os.path.join(log_dir, f)
                                    size = os.path.getsize(fpath)
                                    console.print(f"  • {f} ({size} bytes)")
                        except Exception as exc:
                            console.print(f"[bold red]Failed to list log files: {exc}[/bold red]")
                    else:
                        console.print("[bold red]Usage: /logs [view|list][/bold red]")
                    continue

                if cmd in ("/symbols", "/symbol", "/sym"):
                    if not arg:
                        console.print("[bold red]Usage: /symbols <name>  — look up a symbol in the index.[/bold red]")
                    else:
                        handled = agent._handle_symbols_query(f"where is {arg} defined")
                        if not handled:
                            console.print(f"[dim]Symbol '{arg}' not in index. Falling back to LLM search...[/dim]")
                            agent.process_prompt(f"where is {arg} defined")
                    continue

                if cmd in ("/model", "/m"):
                    if not arg:
                        console.print(Panel(
                            f"[bold yellow]Current Active Models per Role:[/bold yellow]\n\n"
                            f"  • Planner : [bold cyan]{current_config.planner_models}[/bold cyan]\n"
                            f"  • Coder   : [bold cyan]{current_config.coder_models}[/bold cyan]\n"
                            f"  • Verifier: [bold cyan]{current_config.verifier_models}[/bold cyan]\n"
                            f"  • Reviewer: [bold cyan]{current_config.reviewer_models}[/bold cyan]\n"
                            f"  • Summary : [bold cyan]{current_config.summary_models}[/bold cyan]",
                            title="[bold yellow]NERO Active Models[/bold yellow]",
                            border_style="yellow"
                        ))
                    else:
                        from .onboarding import resolve_model_with_provider
                        resolved = resolve_model_with_provider(arg)
                        
                        if resolved.startswith("google/"):
                            all_gemini = ["google/gemini-3.5-flash", "google/gemini-3.6-flash", "google/gemini-3.1-flash-lite", "google/gemini-3-flash-preview", "google/gemini-3.5-flash-lite"]
                            if resolved in all_gemini:
                                all_gemini.remove(resolved)
                            gemini_chain = [resolved] + all_gemini
                            planners = gemini_chain + ["openai/gpt-4o-mini", "openrouter/free"]
                            coders = [resolved, "google/gemini-3.6-flash", "google/gemini-3-flash-preview", "openai/gpt-4o", "anthropic/claude-3-5-sonnet-latest"]
                            verifiers = [resolved, "google/gemini-3.5-flash-lite", "google/gemini-3.1-flash-lite", "openai/gpt-4o-mini"]
                            reviewers = [resolved, "google/gemini-3.6-flash", "google/gemini-3-flash-preview", "openai/gpt-4o-mini"]
                            summaries = [resolved, "google/gemini-3.5-flash-lite", "openai/gpt-4o-mini"]
                        elif resolved.startswith("openai/"):
                            planners = [resolved, "openai/gpt-4o-mini"]
                            coders = [resolved, "openai/gpt-4o"]
                            verifiers = [resolved, "openai/gpt-4o-mini"]
                            reviewers = [resolved, "openai/gpt-4o-mini"]
                            summaries = [resolved, "openai/gpt-4o-mini"]
                        elif resolved.startswith("anthropic/"):
                            planners = [resolved, "openai/gpt-4o-mini"]
                            coders = [resolved, "anthropic/claude-3-5-sonnet-latest"]
                            verifiers = [resolved, "openai/gpt-4o-mini"]
                            reviewers = [resolved, "openai/gpt-4o-mini"]
                            summaries = [resolved, "openai/gpt-4o-mini"]
                        else:
                            planners = [resolved]
                            coders = [resolved]
                            verifiers = [resolved]
                            reviewers = [resolved]
                            summaries = [resolved]

                        current_config.planner_models = planners
                        current_config.coder_models = coders
                        current_config.verifier_models = verifiers
                        current_config.reviewer_models = reviewers
                        current_config.summary_models = summaries
                        
                        import json
                        from . import config as cfg
                        settings = cfg.load_global_settings()
                        settings.update({
                            "planner_models": planners,
                            "coder_models": coders,
                            "verifier_models": verifiers,
                            "reviewer_models": reviewers,
                            "summary_models": summaries,
                        })
                        cfg.ensure_nero_dirs()
                        with open(cfg.SETTINGS_PATH, "w", encoding="utf-8") as f:
                            json.dump(settings, f, indent=2)
                        
                        agent = AgentCore(current_config, memory, logger)
                        
                        console.print(Panel(
                            f"[bold green]✓ Active model successfully updated to [cyan]{resolved}[/cyan]![/bold green]\n\n"
                            f"  • Planner : [bold cyan]{current_config.planner_models}[/bold cyan]\n"
                            f"  • Coder   : [bold cyan]{current_config.coder_models}[/bold cyan]\n"
                            f"  • Verifier: [bold cyan]{current_config.verifier_models}[/bold cyan]\n"
                            f"  • Reviewer: [bold cyan]{current_config.reviewer_models}[/bold cyan]\n"
                            f"  • Summary : [bold cyan]{current_config.summary_models}[/bold cyan]",
                            title="[bold green]Model Switched[/bold green]",
                            border_style="green"
                        ))
                    continue

                if cmd == "/repo":
                    if not arg:
                        console.print("[bold red]Please specify repo path or URL. Example: /repo ./my_app[/bold red]")
                        continue
                    current_config.repo_path = arg
                    memory.repo_path = arg
                    memory.repo_context = None
                    console.print(f"[bold green]Target repository updated to: {arg}[/bold green]")
                    continue

                console.print(f"[bold red]Unknown slash command '{cmd}'. Type /help for available commands.[/bold red]")
                continue

            if user_input.lower() in ["exit", "quit"]:
                console.print("[dim]Goodbye from NERO![/dim]")
                break

            try:
                agent.process_prompt(user_input)
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Task execution cancelled by user. Returning to REPL prompt.[/bold yellow]\n")
            except Exception as exc:
                console.print(f"\n[bold red]Error: {exc}[/bold red]\n")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye from NERO![/dim]")
            break


@app.callback(invoke_without_command=True)
def main_menu(
    ctx: typer.Context,
    request: Optional[str] = typer.Option(None, "--request", "-r", help="Optional initial change request."),
    repo: str = typer.Option(DEFAULT_REPO_URL, "--repo", help="Git repo URL or local directory path."),
    dest: str = typer.Option("./target_repo", "--dest", "-d", help="Local destination directory."),
):
    """Default entrypoint launching NERO REPL shell."""
    if ctx.invoked_subcommand is not None:
        return

    from .onboarding import run_onboarding_if_needed
    run_onboarding_if_needed()

    config = build_config(dest=dest)
    start_repl_session(initial_request=request, initial_repo=repo, initial_dest=dest, config=config)


@app.command()
def auto():
    """Execute default autonomous benchmark task immediately."""
    from .onboarding import run_onboarding_if_needed
    run_onboarding_if_needed()

    config = build_config()
    start_repl_session(initial_request=DEFAULT_REQUEST, config=config)


@app.command()
def run(
    request: Optional[str] = typer.Option(
        None,
        "--request",
        "-r",
        help="Product or technical change request.",
    ),
    repo: str = typer.Option(
        DEFAULT_REPO_URL,
        "--repo",
        help="Git repo URL or local directory path.",
    ),
    dest: str = typer.Option(
        "./target_repo",
        "--dest",
        "-d",
        help="Local directory destination for cloning.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Use a single specified model for all agent roles.",
    ),
    planner_models: Optional[str] = typer.Option(
        None,
        "--planner-models",
        help="Comma-separated model fallback chain for planning.",
    ),
    coder_models: Optional[str] = typer.Option(
        None,
        "--coder-models",
        help="Comma-separated model fallback chain for coding.",
    ),
    verifier_models: Optional[str] = typer.Option(
        None,
        "--verifier-models",
        help="Comma-separated model fallback chain for verification.",
    ),
    reviewer_models: Optional[str] = typer.Option(
        None,
        "--reviewer-models",
        help="Comma-separated model fallback chain for reviewer.",
    ),
    summary_models: Optional[str] = typer.Option(
        None,
        "--summary-models",
        help="Comma-separated model fallback chain for summary.",
    ),
    max_iterations: int = typer.Option(
        15,
        "--max-iterations",
        help="Tool execution loop iteration cap.",
    ),
    max_repair_attempts: int = typer.Option(
        3,
        "--max-repair-attempts",
        help="Self-correction repair loop limit.",
    ),
    verifier_command: Optional[str] = typer.Option(
        None,
        "--verifier-command",
        help="Custom build/test command to run for verification.",
    ),
    skip_tests: bool = typer.Option(
        False,
        "--skip-tests",
        help="Skip automated test verification.",
    ),
):
    """Run NERO agent directly with explicit command line parameters."""
    from .onboarding import run_onboarding_if_needed
    run_onboarding_if_needed()

    config = build_config(
        model,
        planner_models,
        coder_models,
        verifier_models,
        reviewer_models,
        summary_models,
        max_iterations,
        max_repair_attempts,
        dest,
    )
    start_repl_session(initial_request=request, initial_repo=repo, initial_dest=dest, config=config)


if __name__ == "__main__":
    app()
