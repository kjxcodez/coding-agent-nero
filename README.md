```text
   ███╗   ██╗███████╗██████╗  ██████╗
   ████╗  ██║██╔════╝██╔══██╗██╔═══██╗
   ██╔██╗ ██║█████╗  ██████╔╝██║   ██║
   ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║
   ██║ ╚████║███████╗██║  ██║╚██████╔╝
   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝
```

# NERO (Evolution Edition) — Autonomous AI Coding Agent CLI

> 📖 **Walkthrough & Demo**: Want to see NERO in action? Check out the step-by-step [Walkthrough & Demo](DEMO.md) featuring a real, unedited execution session!

NERO is an autonomous, agentic command-line assistant designed to analyze, modify, repair, and verify software codebases. It executes a complete planning-execution-verification-review lifecycle directly in your terminal, communicating with leading LLM providers (Google Gemini, OpenAI, Anthropic, and OpenRouter).

---

## Key Features

- **Interactive Onboarding**: Automatic API credential setup and model selection on first launch.
- **Verification Game Protection (Anti-Reward Hacking)**: Strict constraints blocking the AI coder from editing test configuration files (like `package.json` test scripts) to cheat validation.
- **Smart Fallback Verification**: If a repository doesn't have a test suite configured, NERO automatically runs:
  1. Syntax check validation (e.g. `node -c` for Javascript files).
  2. Subprocess boot check (starts the app/server for 2.0s to confirm it runs without crashing).
- **Workspace Privacy & Hallucination Prevention**: Automatically masks absolute host paths (e.g., `C:\Users\username\...`) to protect user identity and prevent the LLM from confabulating remote repository URLs.
- **Scoped Sandbox Tooling**: Prevents structural errors by disabling repository cloning (`clone_repo`) once the workspace is running.
- **Full State Introspection REPL**: Instant commands to query routes, codebase architecture, symbol indices, and logs.

---

## Installation

### Prerequisites
- Python >= 3.8
- Git (system path)
- Node.js (optional, for syntax/boot fallbacks on Node codebases)

### 1. Clone & Set Up Virtual Env
Clone this repository to your local system and navigate to the project directory:
```bash
git clone <repository-url>
cd coding-agent-nero

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

### 2. Run the Installation Script
NERO can be installed globally/locally in editable mode so the `nero` command is available anywhere on your system.

- **Windows (PowerShell/CMD)**:
  ```cmd
  install_cli.bat
  ```
- **macOS/Linux**:
  ```bash
  chmod +x install_cli.sh
  ./install_cli.sh
  ```

Alternatively, you can manually install it in editable mode:
```bash
pip install -e .
```

---

## Quick Start

### 1. Run NERO
Launch NERO directly in your terminal. You can specify a local folder or a Git URL:
```bash
# Start NERO in the current directory
nero

# Start NERO and clone/open a specific repository
nero https://github.com/callicoder/node-easy-notes-app
```

### 2. Onboarding Flow
On your first run, NERO guides you through an interactive setup:
1. Select your preferred LLM Provider (Google Gemini, OpenAI, Anthropic, or OpenRouter).
2. Enter your API Key (which is verified with a test connection).
3. Select your default models.
4. Settings are stored globally at `~/.nero/settings.json` and API keys are stored in `~/.nero/credentials.json`.

---

## Slash Commands

Within the NERO shell (`nero >:`), you can run the following built-in commands:

| Command | Description |
|---|---|
| `/help` | Display the commands panel and shortcuts. |
| `/status` / `/memory` | View active workspace paths, turns, edits log, and cache state. |
| `/diff` | View active git modifications made in this session. |
| `/undo` | Roll back all local edits and restore the repo to the git baseline. |
| `/plan` | View details of the active task modification plan. |
| `/resume` | View details of the active task modification plan and resume execution. |
| `/architecture` | View the structural map of the repository (Models, Controllers, Entrypoints). |
| `/routes` | List all detected API endpoints (supports Express.js, FastAPI, Flask, Django, etc.). |
| `/symbols <query>` | Query the indexed code symbols (classes, functions, methods). |
| `/model [name]` | View active LLM chain configurations or dynamically switch model providers. |
| `/logs [session_id/view]` | View active session logs or list history files from `~/.nero/logs/`. |

---

## The Execution Pipeline

When you ask NERO to make a change (e.g. *"add tags support to the POST endpoint"*), NERO triggers a robust 4-phase lifecycle:

```mermaid
graph TD
    A[Phase 1: Planning] --> B[Phase 2: Execution]
    B --> C[Phase 3: Verification]
    C -->|Failed tests| D[Phase 4: Automatic Repair]
    D -->|Retests| C
    C -->|Passed| E[Phase 5: Code Review]
    E -->|Approved & Gated| F[Complete & Save]
```

1. **Planning**: NERO analyzes the workspace and drafts an incremental list of modification steps.
2. **Execution**: The Coder agent runs file editing tools (`replace_text`, `write_file`) step-by-step.
3. **Verification**: NERO runs the project test suite or fallbacks (syntax + boot checks).
4. **Repair**: If tests fail, the Repair Controller triggers a repair loop to fix errors.
5. **Review**: The Reviewer Agent audits the code changes against the user intent, pending steps, and repair logs, approving or disapproving the work.

---

## Limitations & Known Behaviors

Based on real-world session audits using free-tier LLM providers, keep the following behaviors and limitations in mind:

- **Model Execution Caps (`max_iterations`)**: Weak or free-tier models (e.g. models in `openrouter/free`) may exhaust the iteration limit (default: 15) before emitting a `DONE:` signal. This happens because weaker models tend to repeat file reads rather than acting on existing context. You can increase `max_iterations` in your settings, but using a stronger model (Gemini Flash, GPT-4o, Claude) is highly recommended.
- **Boot Check Database Dependencies**: NERO's boot check verification (`node server.js` or equivalent) will fail with exit code 1 if the target project depends on an active database (like MongoDB) that isn't running locally. NERO cannot distinguish between code errors and missing host infrastructure.
  - *Workaround*: Ensure local databases/services are running before launching NERO, or write mock tests so NERO uses `npm test` verification instead.
- **Ambiguous Prompts**: If NERO is cancelled mid-run, generic follow-ups like "continue" may be classified as general conversation, starting a new context scan instead of resuming. Use the `/resume` command to explicitly pick up where NERO left off.
- **API Rate Limits**: Standard free-tier keys on OpenRouter have a limit of 50 requests per day. When hit, NERO's fallback chain will attempt to rotate through available models, but if all free models are rate-limited, execution will halt.

For a full breakdown of these behaviors captured in a live test, see the [Demo Walkthrough](demo.md).

---

## Running Tests & Static Analysis

Before submitting pull requests or making releases, verify repository integrity locally:

### 1. Setup Dev Dependencies
Install the package along with its optional development dependencies:
```bash
pip install -e .[dev]
```

### 2. Run Linting and Formatting Check
We use `ruff` for fast python linting and code formatting validation:
```bash
# Check code style issues and fixes
ruff check agent/ tests/

# Validate formatting
ruff format --check agent/ tests/
```

### 3. Run Static Type Checking
We use `mypy` for static type verification:
```bash
mypy agent/
```

### 4. Run Dependency Security Audit
We use `pip-audit` to detect known CVE vulnerabilities in our dependency tree:
```bash
pip-audit
```

### 5. Run the Test Suite
Verify that the NERO CLI functioning and verifications pass successfully:
```bash
python -m pytest
```

---

## Development & CI/CD Pipeline

NERO maintains a production-grade automated engineering pipeline:

### 1. CI Pipeline (`ci.yml`)
Runs automatically on every push or pull request on all branches across **Ubuntu**, **Windows**, and **macOS** on Python **3.8, 3.9, 3.10, 3.11, and 3.12**:
1. Checks formatting & lint rules (`ruff`).
2. Runs static type validation (`mypy`).
3. Conducts security vulnerability check (`pip-audit`).
4. Verifies the package builds cleanly (`python -m build`).
5. Performs CLI Smoke Tests (installs from wheel, runs `nero --version` and `nero --help`).
6. Executes the entire unit test suite (`pytest`).

### 2. Release & Changelog Pipeline (`release.yml`)
When a version tag (e.g. `v1.0.1`) is pushed:
1. Triggers the automated changelog script to parse conventional commits since the last tag.
2. Commits and pushes the updated `CHANGELOG.md` directly to `main`.
3. Builds source and binary wheel distributions.
4. Generates a new GitHub Release, attaches the built wheel and tarball assets, and populates the release description with conventional release notes.

### 3. Versioning Strategy
We adhere to **Semantic Versioning (SemVer)** (e.g., `MAJOR.MINOR.PATCH`).
To release a new version:
1. Update the version number in `pyproject.toml`.
2. Commit the change.
3. Tag the commit (e.g., `git tag v1.0.1`).
4. Push the tag to trigger the Release Pipeline:
   ```bash
   git push origin v1.0.1
   ```

### 4. Manual Changelog Generation
You can also preview or generate the changelog locally:
```bash
# Preview changes since the last tag (dry run)
python scripts/generate_changelog.py --release-version v1.0.1 --dry-run

# Write updates to CHANGELOG.md locally
python scripts/generate_changelog.py --release-version v1.0.1
```

---

## Contributing & License

Contributions are highly welcome! Please check out [CONTRIBUTING.md](file:///C:/Users/91637/Desktop/Projects/coding-agent-nero/CONTRIBUTING.md) for guidelines.

This project is licensed under the MIT License — see the [LICENSE](file:///C:/Users/91637/Desktop/Projects/coding-agent-nero/LICENSE) file for details.

### 💸 API Budget Disclaimer / Sponsor Call
Google Gemini and OpenRouter integrations are fully tested and verified. However, **no money** was left to verify OpenAI and Anthropic integrations (our developer pockets are dry!). If you want to sponsor our API keys or verify those providers for us, check out the disclaimer in [CONTRIBUTING.md](file:///C:/Users/91637/Desktop/Projects/coding-agent-nero/CONTRIBUTING.md)!

