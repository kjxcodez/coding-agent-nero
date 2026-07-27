"""
SessionMemory — typed, structured replacement for WorkingMemory.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..intelligence.context import RepositoryContext
from .edit_log import EditLog
from .snapshot import FileSnapshot


@dataclass
class ConversationTurn:
    role: str
    content: str


@dataclass
class GitState:
    """Snapshot of git state at session start."""
    branch: str = "unknown"
    baseline_commit: str = ""
    current_commit: str = ""
    is_dirty: bool = False

    @classmethod
    def capture(cls, repo_path: str) -> "GitState":
        def run(args: List[str]) -> str:
            try:
                result = subprocess.run(
                    ["git"] + args,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=5,
                )
                return result.stdout.strip() if result.returncode == 0 else ""
            except Exception:
                return ""

        commit = run(["rev-parse", "HEAD"])
        branch = run(["branch", "--show-current"]) or "unknown"
        status = run(["status", "--porcelain"])

        return cls(
            branch=branch,
            baseline_commit=commit,
            current_commit=commit,
            is_dirty=bool(status),
        )

    def refresh(self, repo_path: str) -> None:
        def run(args: List[str]) -> str:
            try:
                result = subprocess.run(
                    ["git"] + args,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=5,
                )
                return result.stdout.strip() if result.returncode == 0 else ""
            except Exception:
                return ""

        self.current_commit = run(["rev-parse", "HEAD"])
        status = run(["status", "--porcelain"])
        self.is_dirty = bool(status)


@dataclass
class SessionMemory:
    """Typed, structured session state for NERO."""

    repo_path: str
    repo_context: Optional[RepositoryContext] = None

    _file_cache: Dict[str, str] = field(default_factory=dict)
    _file_snapshots: Dict[str, FileSnapshot] = field(default_factory=dict)

    conversation_history: List[ConversationTurn] = field(default_factory=list)
    edit_log: EditLog = field(default_factory=EditLog)
    git_state: GitState = field(default_factory=lambda: GitState())

    _turn_count: int = 0
    current_plan: Optional[Any] = None

    def cache_file(self, rel_path: str, content: str) -> None:
        norm = rel_path.replace("\\", "/")
        self._file_cache[norm] = content
        self._file_snapshots[norm] = FileSnapshot.from_read(norm, content)

    def get_cached_file(self, rel_path: str) -> Optional[str]:
        norm = rel_path.replace("\\", "/")
        return self._file_cache.get(norm)

    def invalidate_file(self, rel_path: str) -> None:
        norm = rel_path.replace("\\", "/")
        self._file_cache.pop(norm, None)
        self._file_snapshots.pop(norm, None)

    def has_file_changed_externally(self, rel_path: str, current_content: str) -> bool:
        norm = rel_path.replace("\\", "/")
        snap = self._file_snapshots.get(norm)
        if snap is None:
            return False
        return snap.has_changed(current_content)

    def cache_write(self, rel_path: str, content: str) -> None:
        norm = rel_path.replace("\\", "/")
        self._file_cache[norm] = content
        self._file_snapshots[norm] = FileSnapshot.from_write(norm, content)

    def record_edit(
        self,
        path: str,
        previous_content: str,
        timestamp: str,
        operation: str = "write",
        new_content: str = "",
        description: str = "",
    ) -> None:
        self.edit_log.record(
            path=path,
            old_content=previous_content,
            new_content=new_content or previous_content,
            operation=operation,
            git_commit=self.git_state.current_commit,
            description=description,
        )
        self.invalidate_file(path)

    def get_edits_summary(self) -> str:
        return self.edit_log.summary()

    @property
    def recent_edits(self) -> List[Any]:
        return self.edit_log.entries()

    @property
    def inspected_files_cache(self) -> Dict[str, str]:
        return self._file_cache

    def add_turn(self, role: str, content: str) -> None:
        self.conversation_history.append(ConversationTurn(role=role, content=content))
        self._turn_count += 1
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

    def format_history_for_llm(self) -> List[Dict[str, str]]:
        return [{"role": t.role, "content": t.content} for t in self.conversation_history]

    def capture_git_state(self) -> None:
        self.git_state = GitState.capture(self.repo_path)

    def refresh_git_state(self) -> None:
        self.git_state.refresh(self.repo_path)

    def reset_after_undo(self) -> None:
        self._file_cache.clear()
        self._file_snapshots.clear()
        self.edit_log.clear()
        self.refresh_git_state()

    def reset_for_new_repo(self) -> None:
        self.repo_context = None
        self._file_cache.clear()
        self._file_snapshots.clear()
        self.edit_log.clear()
        self.conversation_history.clear()
        self.git_state = GitState()

    def format_memory_report(self) -> str:
        ctx = self.repo_context
        git = self.git_state

        repo_line = (
            f"{ctx.primary_language} / {', '.join(ctx.detected_frameworks) or 'no framework'}"
            if ctx else "Not yet analyzed"
        )
        git_line = (
            f"Branch: {git.branch}  "
            f"Baseline: {git.baseline_commit[:7] or 'N/A'}  "
            f"Current: {git.current_commit[:7] or 'N/A'}  "
            f"{'DIRTY' if git.is_dirty else 'CLEAN'}"
        )
        cached_files = len(self._file_cache)
        dirty_snaps = sum(1 for s in self._file_snapshots.values() if s.is_dirty)

        lines = [
            "### NERO Session Memory",
            "",
            f"**Workspace** : `{self.repo_path}`",
            f"**Repository** : {repo_line}",
            f"**Git state**  : {git_line}",
            f"**Turns**      : {self._turn_count}",
            f"**Cached files**: {cached_files} read ({dirty_snaps} dirty / pending confirm)",
            "",
            "**Edit log**:",
            self.edit_log.summary() or "  No edits.",
        ]

        if self.conversation_history:
            lines += [
                "",
                f"**Conversation**: {len(self.conversation_history)} turn(s) in context",
            ]

        return "\n".join(lines)
