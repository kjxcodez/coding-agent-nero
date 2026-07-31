"""
Unified Autonomous Reasoning Agent Engine for NERO.
"""

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from .config import AgentConfig
from .context import WorkingMemory
from .core.intent import Intent, IntentRouter
from .intelligence.context import RepositoryContext
from .intelligence.scanner import RepositoryScanner
from .llm.router import ModelRouter
from .pipeline import PipelineOrchestrator
from .repo import RepositoryManager
from .tools import ToolRegistry
from .utils.logger import AgentLogger

_SYMBOL_PATTERNS = [
    re.compile(r"where is\s+(\w+)", re.I),
    re.compile(r"find\s+(?:the\s+)?(?:function|class|method|definition\s+of)?\s*(\w+)", re.I),
    re.compile(r"locate\s+(\w+)", re.I),
    re.compile(r"definition\s+of\s+(\w+)", re.I),
    re.compile(r"/symbols?\s+(\w+)", re.I),
]


SYSTEM_AGENT_PROMPT = """You are NERO, a Senior Staff Engineer and Autonomous AI Coding Agent.

You have access to a full suite of sandboxed software engineering tools:
- clone_repo           : Clone a remote Git repository URL or bind a local workspace path.
- list_files           : List files in a directory.
- read_file            : Read file contents.
- write_file           : Write full file contents.
- create_file          : Create a new file.
- replace_text         : Replace exact text in a file (preferred for targeted edits).
- search_code_content  : Search a regex/substring pattern across codebase file contents.
- search_filenames     : Search for filenames matching a glob/substring pattern.
- search_symbols       : Search the repository symbol index for class, function, or method definitions.
- search_routes        : Search detected HTTP API endpoints and route handlers.
- git_diff             : Show active git diff.
- git_status           : Show active git status.
- run_command          : Run a safe build or test command.

AUTONOMOUS BEHAVIOR RULES:
1. Reason step by step about what the user wants.
2. You receive a detailed Repository Intelligence context block before each request.
   Use it — do NOT re-discover information that is already provided.
3. Only call read_file or search tools for information NOT present in the context block.
4. For code modifications: make minimal targeted edits (prefer replace_text over write_file).
5. Be concise, technical, helpful, and professional.
6. After completing any modification: briefly summarise what you changed and why.
"""


class AgentCore:
    """Stateful autonomous reasoning engine for NERO."""

    def __init__(
        self,
        config: AgentConfig,
        memory: WorkingMemory,
        logger: Optional[AgentLogger] = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.logger = logger or AgentLogger(verbose=config.verbose)
        self.repo_mgr = RepositoryManager(config)
        self.router = ModelRouter(config)
        self._scanner = RepositoryScanner(config)
        self._intent_router = IntentRouter()

        self._tool_registry: Optional[ToolRegistry] = None
        self._orchestrator: Optional[PipelineOrchestrator] = None

    def ensure_repository_context(self) -> RepositoryContext:
        current_abs = os.path.abspath(self.config.repo_path)

        if self.memory.repo_context is None or self.memory.repo_context.repo_path != current_abs:
            self.logger.progress("Building repository intelligence map (routes · symbols · env)...")
            abs_path = self.repo_mgr.prepare_repository(self.memory.repo_path, self.config.repo_path)
            self.memory.repo_context = self._scanner.scan(abs_path)
            self.memory.repo_path = abs_path
            self.memory.capture_git_state()

            self._tool_registry = ToolRegistry(self.config, abs_path, memory=self.memory)

        return self.memory.repo_context

    def _get_tool_registry(self, ctx: RepositoryContext) -> ToolRegistry:
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry(self.config, ctx.repo_path, memory=self.memory)
        return self._tool_registry

    def _get_orchestrator(self, ctx: RepositoryContext) -> PipelineOrchestrator:
        if self._orchestrator is None:
            tool_registry = self._get_tool_registry(ctx)
            self._orchestrator = PipelineOrchestrator(
                config=self.config,
                router=self.router,
                tool_registry=tool_registry,
                logger=self.logger,
            )
        return self._orchestrator

    def process_prompt(self, user_prompt: str) -> None:
        intent = self._intent_router.classify(user_prompt)
        self.logger.progress(f"Intent: {intent.value}")
        self.logger.log_event("intent_classified", {"prompt": user_prompt, "intent": intent.value})

        inline_dispatch = {
            Intent.STATUS: self._handle_status_query,
            Intent.HELP: self._handle_help_query,
            Intent.DIFF: self._handle_diff_query,
            Intent.UNDO: self._handle_undo,
            Intent.ARCHITECTURE: self._handle_architecture_query,
            Intent.RESUME: self._handle_resume,
            Intent.CONTEXT: self._handle_context_query,
            Intent.ROUTES: self._handle_routes_query,
        }
        if intent in inline_dispatch:
            inline_dispatch[intent]()
            return

        if intent == Intent.SYMBOLS:
            handled = self._handle_symbols_query(user_prompt)
            if handled:
                return
            intent = Intent.EXPLAIN

        workspace_ready = self._workspace_exists()

        if not workspace_ready:
            if intent == Intent.REPOSITORY:
                self._run_no_workspace_loop(user_prompt)
            elif intent in (Intent.CONVERSATION, Intent.EXPLAIN):
                self._run_no_workspace_conversation_loop(user_prompt)
            else:
                self._show_no_workspace_message()
            return

        ctx = self.ensure_repository_context()
        tool_registry = self._get_tool_registry(ctx)

        if intent == Intent.MODIFY:
            self._run_modify_pipeline(user_prompt, ctx)
            return

        all_schemas = tool_registry.get_openai_schemas()
        tool_names = self._intent_router.get_tool_names(intent)
        tool_schemas = (
            all_schemas if tool_names is None else [s for s in all_schemas if s["function"]["name"] in tool_names]
        )

        tools_desc = "all" if tool_names is None else str(len(tool_schemas))
        self.logger.progress(f"Tools: {tools_desc} available for this request")

        edit_summary = self.memory.edit_log.format_for_llm()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_AGENT_PROMPT},
            {"role": "system", "content": ctx.format_context_summary()},
        ]
        if self.memory.edit_log.count() > 0:
            messages.append({"role": "system", "content": edit_summary})
        messages.extend(self.memory.format_history_for_llm())
        messages.append({"role": "user", "content": user_prompt})

        self.logger.progress("NERO thinking...")

        for _step in range(1, self.config.max_iterations + 1):
            response = self.router.chat("coder", messages, tools=tool_schemas, stream=True)

            if not response.tool_calls:
                final_text = response.content or ""
                self.memory.add_turn("user", user_prompt)
                self.memory.add_turn("assistant", final_text)
                if not response.streamed:
                    self.logger.markdown(final_text)
                break

            if response.assistant_message:
                messages.append(response.assistant_message)
            else:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

            for tc in response.tool_calls:
                tool_result = tool_registry.dispatch(tc.name, tc.arguments)
                summary_snippet = tool_result.replace("\n", " ")[:120]
                self.logger.tool(tc.name, tc.arguments, summary_snippet)

                if tc.name == "clone_repo" and "Successfully" in tool_result:
                    self.memory.repo_context = None
                    self._tool_registry = None
                    self._orchestrator = None
                    ctx = self.ensure_repository_context()
                    tool_registry = self._get_tool_registry(ctx)
                    tool_schemas = tool_registry.get_openai_schemas()

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": tool_result,
                    }
                )
        else:
            self.logger.warning("Reached maximum interaction loop iterations without a final response.")

    def _workspace_exists(self) -> bool:
        """Returns True if a valid workspace directory is configured and accessible."""
        path = os.path.abspath(self.config.repo_path)
        # A path is valid if it exists as a directory and is accessible
        return os.path.isdir(path)

    def _show_no_workspace_message(self) -> None:
        path = os.path.abspath(self.config.repo_path)
        self.logger.markdown(
            f"**No workspace found** at `{path}`\n\n"
            "NERO needs a directory to work with. You can:\n"
            "  • **Clone a repo**: `clone https://github.com/owner/repo`\n"
            "  • **Switch to an existing local directory**: `/repo ./my-project`\n"
            "  • **Run NERO in a project folder directly**: `cd my-project && python -m agent.main`\n"
        )

    def _run_no_workspace_loop(self, user_prompt: str) -> None:
        tool_registry = ToolRegistry(self.config, ".", memory=self.memory)
        all_schemas = tool_registry.get_openai_schemas()
        clone_schemas = [s for s in all_schemas if s["function"]["name"] == "clone_repo"]

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_AGENT_PROMPT},
            {
                "role": "system",
                "content": (
                    "No repository is currently loaded. "
                    "Help the user clone or load a repository using the clone_repo tool. "
                    "If no URL or path was given in the user message, ask for one."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        for _step in range(1, self.config.max_iterations + 1):
            response = self.router.chat("coder", messages, tools=clone_schemas, stream=True)

            if not response.tool_calls:
                final_text = response.content or ""
                self.memory.add_turn("user", user_prompt)
                self.memory.add_turn("assistant", final_text)
                if not response.streamed:
                    self.logger.markdown(final_text)
                break

            if response.assistant_message:
                messages.append(response.assistant_message)
            else:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

            for tc in response.tool_calls:
                tool_result = tool_registry.dispatch(tc.name, tc.arguments)
                self.logger.tool(tc.name, tc.arguments, tool_result[:120])

                if tc.name == "clone_repo" and "Successfully" in tool_result:
                    cloned_path = tool_result.split("workspace: ")[-1].strip()
                    self.config.repo_path = os.path.abspath(cloned_path)
                    self.memory.repo_context = None
                    self._tool_registry = None
                    self._orchestrator = None
                    try:
                        self.ensure_repository_context()
                    except Exception as exc:
                        self.logger.warning(f"Post-clone scan warning: {exc}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": tool_result,
                    }
                )
        else:
            self.logger.warning("Reached maximum interaction loop iterations without a final response.")

    def _run_no_workspace_conversation_loop(self, user_prompt: str) -> None:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_AGENT_PROMPT},
            {
                "role": "system",
                "content": (
                    "No repository workspace is currently loaded. "
                    "You cannot access any codebase or tools right now. "
                    "You are conversing with the user. You can answer general questions. "
                    "If the user wants you to work on a codebase, advise them to use "
                    "the `clone` command or select a workspace directory."
                ),
            },
        ]
        messages.extend(self.memory.format_history_for_llm())
        messages.append({"role": "user", "content": user_prompt})

        self.logger.progress("NERO thinking...")

        response = self.router.chat("coder", messages, stream=True)
        final_text = response.content or ""
        self.memory.add_turn("user", user_prompt)
        self.memory.add_turn("assistant", final_text)
        if not response.streamed:
            self.logger.markdown(final_text)

    def _run_modify_pipeline(self, user_prompt: str, ctx: RepositoryContext) -> None:
        orchestrator = self._get_orchestrator(ctx)
        outcome = orchestrator.run(
            user_request=user_prompt,
            repo_context=ctx,
            memory=self.memory,
        )

        self.memory.current_plan = outcome.plan
        self.memory.add_turn("user", user_prompt)
        self.memory.add_turn(
            "assistant",
            outcome.plan.progress_summary(),
        )

        self.logger.markdown(outcome.format_session_summary())
        self.memory.refresh_git_state()

        # Log completion
        self.logger.log_event(
            "modify_pipeline_completed",
            {
                "success": outcome.success,
                "steps_completed": len(outcome.plan.completed_steps()),
                "steps_total": len(outcome.plan.steps),
                "repair_attempts": outcome.repair_attempts,
            },
        )

    def _handle_help_query(self) -> None:
        from agent.main import show_help_panel

        show_help_panel()

    def _handle_plan_query(self) -> None:
        plan = getattr(self.memory, "current_plan", None)
        if plan is None:
            self.logger.markdown(
                "No active plan. Run a modification request to generate a plan.\n"
                "Example: *add a tags field to the Note model*"
            )
            return
        self.logger.markdown(plan.format_for_display())

    def _handle_architecture_query(self) -> None:
        ctx = self.memory.repo_context
        if not ctx:
            self.logger.markdown("Repository not yet analyzed. Run any prompt to trigger analysis.")
            return

        arch = ctx.architecture_map
        lines = [
            "### Repository Architecture",
            "",
            f"**Pattern**  : {arch.pattern}",
            f"**Framework** : {arch.primary_framework}",
            f"**Language**  : {ctx.primary_language}",
        ]

        if ctx.detected_frameworks:
            lines.append(f"**Libraries** : {', '.join(ctx.detected_frameworks)}")
        if ctx.databases_and_orms:
            lines.append(f"**Databases** : {', '.join(ctx.databases_and_orms)}")
        if ctx.package_managers:
            lines.append(f"**Pkg Mgrs**  : {', '.join(ctx.package_managers)}")
        if ctx.build_tools:
            lines.append(f"**Build**     : {', '.join(ctx.build_tools)}")

        if arch.component_graph:
            lines += ["", "**Component Graph**:"]
            for layer, files in arch.component_graph.items():
                lines.append(
                    f"  `{layer}` → {', '.join(files[:5])}" + (f" (+{len(files) - 5} more)" if len(files) > 5 else "")
                )

        def _section(title: str, items: list) -> None:
            if items:
                lines.append("")
                lines.append(f"**{title}** ({len(items)}):")
                for item in items[:12]:
                    lines.append(f"  • `{item}`")
                if len(items) > 12:
                    lines.append(f"  *... and {len(items) - 12} more*")

        _section("Entry Points", ctx.entrypoints)
        _section("Models", ctx.models)
        _section("Controllers / Routes", ctx.controllers_or_routes)
        _section("Services / Repositories", ctx.services_or_repos)
        _section("Test Files", ctx.test_files)
        _section("Config Files", ctx.config_files)

        if ctx.env_variables:
            lines += ["", f"**Environment Variables** ({len(ctx.env_variables)}):"]
            lines.append("  `" + "`, `".join(ctx.env_variables[:20]) + "`")
            if len(ctx.env_variables) > 20:
                lines.append(f"  *... and {len(ctx.env_variables) - 20} more*")

        if arch.data_flow_summary:
            lines += ["", f"**Data Flow**: {arch.data_flow_summary}"]

        lines += [
            "",
            f"*{ctx.total_files_count} total files · "
            f"{len(ctx.symbols)} symbols indexed · "
            f"{len(ctx.routes)} routes detected*",
        ]
        self.logger.markdown("\n".join(lines))

    def _handle_resume(self) -> None:
        plan = getattr(self.memory, "current_plan", None)

        if plan is None:
            self.logger.markdown(
                "No active plan to resume. Run a modification request first.\n"
                "Example: *add a tags field to the Note model*"
            )
            return

        pending = plan.pending_steps()
        if not pending:
            self.logger.markdown(
                f"Plan '{plan.goal}' is already complete.\n"
                f"{plan.progress_summary()}\n"
                "Use `/undo` to revert, or start a new modification request."
            )
            return

        self.logger.progress(f"Resuming plan '{plan.goal}' — {len(pending)} step(s) remaining...")

        ctx = self.ensure_repository_context()
        orchestrator = self._get_orchestrator(ctx)

        updated_plan, completion_text = orchestrator._executor.execute(
            plan=plan,
            context_summary=ctx.format_context_summary(),
        )
        self.memory.current_plan = updated_plan

        if updated_plan.validation_commands:
            self.logger.progress("Re-verifying after resume...")
            verification = orchestrator._verifier.verify(
                repo_path=ctx.repo_path,
                commands=updated_plan.validation_commands,
            )
            v_status = "passed ✓" if verification.passed else "failed ✗"
            self.logger.markdown(f"{updated_plan.format_for_display()}\n\n**Verification**: {v_status}")
        else:
            self.logger.markdown(updated_plan.format_for_display())

        self.memory.refresh_git_state()

    def _handle_status_query(self) -> None:
        self.logger.markdown(self.memory.format_memory_report())

    def _handle_diff_query(self) -> None:
        if not self._workspace_exists():
            self.logger.markdown("No workspace found. Diff is not available.")
            return
        diff_text = self.repo_mgr.get_diff(self.memory.repo_path)
        self.logger.markdown(f"### Active Git Diff\n```diff\n{diff_text[:6000]}\n```")

    def _handle_context_query(self) -> None:
        ctx = self.memory.repo_context
        if not ctx:
            self.logger.markdown("Repository not yet analyzed. Run any prompt to trigger analysis.")
            return
        self.logger.markdown(f"```\n{ctx.format_context_summary()}\n```")

    def _handle_routes_query(self) -> None:
        ctx = self.memory.repo_context
        if not ctx:
            self.logger.markdown("Repository not yet analyzed.")
            return
        if not ctx.routes:
            self.logger.markdown(
                "No routes detected. NERO currently supports Express.js, FastAPI, Flask, Django, and Next.js."
            )
            return
        route_lines = [f"| {r.method:<7} | {r.path:<40} | {r.handler:<25} | {r.file}:{r.line} |" for r in ctx.routes]
        header = "| Method  | Path                                     | Handler                   | Location         |"
        sep = "|---------|------------------------------------------|---------------------------|------------------|"
        table = "\n".join([header, sep] + route_lines)
        self.logger.markdown(f"### Detected API Routes ({len(ctx.routes)})\n\n{table}")

    def _handle_symbols_query(self, user_prompt: str) -> bool:
        ctx = self.memory.repo_context
        if not ctx or not ctx.symbols:
            return False

        query = None
        for pat in _SYMBOL_PATTERNS:
            m = pat.search(user_prompt)
            if m:
                query = m.group(1)
                break

        if not query:
            return False

        matches = ctx.find_symbol(query)
        if not matches:
            self.logger.markdown(
                f"Symbol `{query}` not found in the index ({len(ctx.symbols)} symbols indexed).\n"
                f"Searching codebase with the LLM..."
            )
            return False

        lines = [f"### Symbol: `{query}`", ""]
        for sym in matches[:10]:
            lines.append(
                f"**{sym.kind.value}** `{sym.name}`  "
                f"→ [{sym.file}:{sym.line}](file://{self.memory.repo_path}/{sym.file})"
            )
            if sym.signature:
                lines.append(f"```\n{sym.signature}\n```")
            if sym.docstring:
                lines.append(f"*{sym.docstring[:200]}*")
            lines.append("")
        self.logger.markdown("\n".join(lines))
        return True

    def _handle_undo(self) -> None:
        if not self._workspace_exists():
            self.logger.error("No workspace found. Undo is not available.")
            return
        self.logger.progress("Undoing last changes via git checkout...")
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=self.memory.repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=self.memory.repo_path,
                check=True,
                capture_output=True,
            )
            self.memory.reset_after_undo()
            self._scanner.invalidate_cache(self.memory.repo_path)
            self.logger.success("Reverted all uncommitted modifications back to clean git baseline.")
        except Exception as exc:
            self.logger.error(f"Undo failed: {exc}")

    def _handle_memory_query(self) -> None:
        self.logger.markdown(self.memory.format_memory_report())
