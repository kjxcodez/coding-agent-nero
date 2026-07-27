"""
FileSnapshot — typed, immutable record of a file read or write observation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FileSnapshot:
    """Immutable record of a file state at a given point in time."""

    path: str
    content_hash: str
    observed_at: str
    is_dirty: bool
    size_bytes: int

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @classmethod
    def from_read(cls, path: str, content: str) -> "FileSnapshot":
        norm = path.replace("\\", "/")
        return cls(
            path=norm,
            content_hash=cls._hash(content),
            observed_at=cls._now(),
            is_dirty=False,
            size_bytes=len(content.encode("utf-8", errors="replace")),
        )

    @classmethod
    def from_write(cls, path: str, content: str) -> "FileSnapshot":
        norm = path.replace("\\", "/")
        return cls(
            path=norm,
            content_hash=cls._hash(content),
            observed_at=cls._now(),
            is_dirty=True,
            size_bytes=len(content.encode("utf-8", errors="replace")),
        )

    def has_changed(self, current_content: str) -> bool:
        return self._hash(current_content) != self.content_hash

    def confirm_written(self, read_back_content: str) -> "FileSnapshot":
        return FileSnapshot(
            path=self.path,
            content_hash=self._hash(read_back_content),
            observed_at=self._now(),
            is_dirty=False,
            size_bytes=len(read_back_content.encode("utf-8", errors="replace")),
        )
