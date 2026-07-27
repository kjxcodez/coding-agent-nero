"""
NERO Onboarding & Setup Wizard.
Interactively guides the user to set up API keys and default models on first start.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

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
            "model": "gemini-2.5-flash",
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

    console.print("[bold yellow]Please select a primary provider:[/bold yellow]")
    console.print("  1. OpenRouter (Access to all models)")
    console.print("  2. OpenAI")
    console.print("  3. Google Gemini (AI Studio)")
    console.print("  4. Anthropic Claude")
    
    choice = Prompt.ask("Select provider [1-4]", choices=["1", "2", "3", "4"], default="1")
    
    providers_map = {
        "1": ("openrouter", "OPENROUTER_API_KEY", [
            "openrouter/free", "google/gemini-2.5-flash", "openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet"
        ]),
        "2": ("openai", "OPENAI_API_KEY", [
            "gpt-4o-mini", "gpt-4o"
        ]),
        "3": ("google", "GEMINI_API_KEY", [
            "gemini-2.5-flash", "gemini-2.5-pro"
        ]),
        "4": ("anthropic", "ANTHROPIC_API_KEY", [
            "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"
        ])
    }
    
    prov_name, key_name, recommended_models = providers_map[choice]
    
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
    console.print("\n[bold yellow]Select a default model for NERO roles:[/bold yellow]")
    for idx, model in enumerate(recommended_models, 1):
        console.print(f"  {idx}. {model}")
    console.print(f"  {len(recommended_models) + 1}. Enter custom model name")
    
    model_choice = Prompt.ask("Choose default model", choices=[str(i) for i in range(1, len(recommended_models) + 2)], default="1")
    if int(model_choice) <= len(recommended_models):
        default_model = recommended_models[int(model_choice) - 1]
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
