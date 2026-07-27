"""
NERO Onboarding & Setup Wizard.
Interactively guides the user to set up API keys and default models on first start.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

def get_key() -> str:
    """Gets a single keypress from the user cross-platform."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):
            ch2 = msvcrt.getch()
            if ch2 == b'H': return "up"
            if ch2 == b'P': return "down"
            if ch2 == b'K': return "left"
            if ch2 == b'M': return "right"
        if ch in (b'\r', b'\n'):
            return "enter"
        try:
            return ch.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A': return "up"
                    if ch3 == 'B': return "down"
                    if ch3 == 'C': return "right"
                    if ch3 == 'D': return "left"
            elif ch in ('\r', '\n'):
                return "enter"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def select_option(options: list[str], title: str = "Select:") -> int:
    """Displays an interactive selection menu using arrow keys."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        console.print(f"[bold yellow]{title}[/bold yellow]")
        for idx, opt in enumerate(options, 1):
            console.print(f"  {idx}. {opt}")
        choice = Prompt.ask("Choose option", choices=[str(i) for i in range(1, len(options) + 1)], default="1")
        return int(choice) - 1

    # Ensure ANSI terminal escape codes are enabled on Windows
    if sys.platform == "win32":
        os.system("")

    selected_idx = 0
    
    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    
    try:
        while True:
            console.print(f"[bold yellow]{title}[/bold yellow]")
            for idx, opt in enumerate(options):
                if idx == selected_idx:
                    console.print(f"  [bold cyan]❯ ● {opt}[/bold cyan]")
                else:
                    console.print(f"    ○ {opt}")
            
            key = get_key()
            if key == "up":
                selected_idx = (selected_idx - 1) % len(options)
            elif key == "down":
                selected_idx = (selected_idx + 1) % len(options)
            elif key == "enter":
                break
                
            sys.stdout.write(f"\033[{len(options) + 1}A")
            sys.stdout.flush()
            
    except KeyboardInterrupt:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        raise
    finally:
        sys.stdout.write(f"\033[{len(options) + 1}A")
        sys.stdout.write("\033[J")
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        
    console.print(f"[bold yellow]{title}[/bold yellow] [bold green]{options[selected_idx]}[/bold green]")
    return selected_idx


def validate_key(provider: str, api_key: str) -> bool:
    """Validates the API key by making a lightweight request using urllib."""
    console.print(f"[dim]Validating key with {provider}...[/dim]")
    
    if provider == "openrouter":
        url = "https://openrouter.ai/api/v1/auth/key"
        headers = {"Authorization": f"Bearer {api_key}"}
        req = urllib.request.Request(url, headers=headers, method="GET")
    elif provider == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    elif provider == "google":
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = json.dumps({
            "model": "gemini-3.5-flash",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    elif provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        data = json.dumps({
            "model": "claude-3-5-haiku-20241022",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    else:
        return False

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                return True
    except urllib.error.HTTPError as e:
        console.print(f"[bold red]Validation error (HTTP {e.code}):[/bold red] {e.reason}")
        try:
            error_body = e.read().decode("utf-8")
            console.print(f"[dim red]{error_body}[/dim red]")
        except Exception:
            pass
    except Exception as e:
        console.print(f"[bold red]Connection error:[/bold red] {e}")
    return False

def run_onboarding_if_needed() -> None:
    """Runs interactive setup if no API keys are detected in config/env."""
    from . import config

    # Check if configured
    if any([config.OPENROUTER_API_KEY, config.OPENAI_API_KEY, config.ANTHROPIC_API_KEY, config.GEMINI_API_KEY]):
        return

    # Onboarding UI
    welcome_text = (
        "[bold cyan]Welcome to NERO! (Evolution Edition)[/bold cyan]\n\n"
        "It looks like you are running NERO for the first time or do not have API keys configured.\n"
        "Let's set up your preferred LLM provider. Configuration will be saved globally under [bold green]~/.nero/[/bold green]."
    )
    console.print(Panel(welcome_text, title="NERO Setup Wizard", border_style="cyan"))

    providers_list = [
        "OpenRouter (Access to all models)",
        "OpenAI",
        "Google Gemini (AI Studio)",
        "Anthropic Claude"
    ]
    
    choice_idx = select_option(providers_list, "Please select a primary provider:")
    
    providers_map = {
        0: ("openrouter", "OPENROUTER_API_KEY", [
            "openrouter/free", "google/gemini-3.5-flash", "openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet"
        ]),
        1: ("openai", "OPENAI_API_KEY", [
            "gpt-4o-mini", "gpt-4o"
        ]),
        2: ("google", "GEMINI_API_KEY", [
            "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-pro", "gemini-3.5-flash-lite"
        ]),
        3: ("anthropic", "ANTHROPIC_API_KEY", [
            "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"
        ])
    }
    
    prov_name, key_name, recommended_models = providers_map[choice_idx]
    
    # Prompt for API Key
    while True:
        api_key = Prompt.ask(f"Enter your [bold cyan]{prov_name}[/bold cyan] API Key (or press Ctrl+C to exit)", password=True).strip()
        if not api_key:
            console.print("[bold red]API Key cannot be empty.[/bold red]")
            continue
            
        validated = validate_key(prov_name, api_key)
        if validated:
            console.print("[bold green]✓ API Key successfully validated![/bold green]")
            break
        else:
            proceed = Confirm.ask("[bold yellow]API Key validation failed. Proceed anyway?[/bold yellow]", default=False)
            if proceed:
                break

    # Select Default Model
    model_options = list(recommended_models) + ["Enter custom model name..."]
    model_choice_idx = select_option(model_options, "Select a default model for NERO roles:")
    
    if model_choice_idx < len(recommended_models):
        default_model = recommended_models[model_choice_idx]
    else:
        default_model = Prompt.ask("Enter custom model identifier").strip()

    # Save credentials
    credentials = config.load_global_credentials()
    credentials[key_name] = api_key
    config.ensure_nero_dirs()
    with open(config.CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump(credentials, f, indent=2)

    # Save settings
    settings = {
        "planner_models": [default_model],
        "coder_models": [default_model],
        "verifier_models": [default_model],
        "reviewer_models": [default_model],
        "summary_models": [default_model],
        "repo_path": "./target_repo",
        "max_iterations": 15,
        "max_repair_attempts": 3,
        "temperature": 0.1,
        "verbose": True
    }
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    console.print(f"\n[bold green]✓ Configuration successfully saved to {config.SETTINGS_PATH} and credentials saved to {config.CREDENTIALS_PATH}![/bold green]")

    # Reload variables in config module so execution can continue
    config.OPENROUTER_API_KEY = credentials.get("OPENROUTER_API_KEY", "")
    config.OPENAI_API_KEY = credentials.get("OPENAI_API_KEY", "")
    config.ANTHROPIC_API_KEY = credentials.get("ANTHROPIC_API_KEY", "")
    config.GEMINI_API_KEY = credentials.get("GEMINI_API_KEY", "")
    
    # Reload AgentConfig default factories
    config._settings = settings
    config._credentials = credentials
    
    console.print("[bold green]Starting NERO session...[/bold green]\n")
