"""
EditLog — typed, per-file log of all modifications made in a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class EditEntry:
    path: str
    timestamp: str
    old_hash: str
    new_hash: str
    old_content: str
    operation: str
    git_commit: str = ""
    description: str = ""


@dataclass
class EditLog:
    """Session-scoped edit log."""

    _entries: List[EditEntry] = field(default_factory=list)
    _first_edit_recorded: Dict[str, bool] = field(default_factory=dict)

    def record(
        self,
        path: str,
        old_content: str,
        new_content: str,
        operation: str = "write",
        git_commit: str = "",
        description: str = "",
    ) -> EditEntry:
        from .snapshot import FileSnapshot

        norm = path.replace("\\", "/")

        store_old = "" if norm in self._first_edit_recorded else old_content
        self._first_edit_recorded[norm] = True

        entry = EditEntry(
            path=norm,
            timestamp=datetime.now().isoformat(),
            old_hash=FileSnapshot._hash(old_content) if old_content else "",
            new_hash=FileSnapshot._hash(new_content),
            old_content=store_old,
            operation=operation,
            git_commit=git_commit,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> List[EditEntry]:
        return list(self._entries)

    def files_edited(self) -> List[str]:
        return sorted(set(e.path for e in self._entries))

    def edits_for_file(self, path: str) -> List[EditEntry]:
        norm = path.replace("\\", "/")
        return [e for e in self._entries if e.path == norm]

    def original_content(self, path: str) -> Optional[str]:
        norm = path.replace("\\", "/")
        for e in self._entries:
            if e.path == norm and e.old_content:
                return e.old_content
        return None

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._first_edit_recorded.clear()

    def summary(self) -> str:
        files = self.files_edited()
        if not files:
            return "No edits made in current session."
        lines = [f"Edited {len(files)} file(s) across {self.count()} operation(s):"]
        for path in files:
            file_edits = self.edits_for_file(path)
            ops = ", ".join(e.operation for e in file_edits)
            lines.append(f"  {path}  [{ops}]")
        return "\n".join(lines)

    def format_for_llm(self, max_files: int = 10) -> str:
        files = self.files_edited()[:max_files]
        if not files:
            return "Session edits: none."
        lines = ["Session edits (this turn):"]
        for path in files:
            edits = self.edits_for_file(path)
            ops = [e.operation for e in edits]
            lines.append(f"  • {path}  ({', '.join(ops)})")
        return "\n".join(lines)
