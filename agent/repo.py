"""
Repository Management Engine for NERO.
Handles repo cloning, workspace resolution, origin URL verification,
wipe/re-clone on target repository change, git diff generation, and changed file tracking.
"""

import os
import shutil
import subprocess
import re
from typing import Optional, List
from .config import AgentConfig


class RepositoryError(Exception):
    """Exception raised for git repository operation failures."""
    pass


class RepositoryManager:
    """Manages target repository workspace and git tracking."""

    def __init__(self, config: AgentConfig):
        self.config = config

    def prepare_repository(self, source: str, dest_dir: Optional[str] = None) -> str:
        """
        Resolves or clones target repository into local directory.
        Re-clones automatically if a new URL is provided that differs from active clone.
        """
        # If dest_dir is already a local directory with files, reuse it immediately
        if dest_dir and os.path.isdir(dest_dir):
            if os.path.isdir(os.path.join(dest_dir, ".git")) or os.path.isfile(os.path.join(dest_dir, "package.json")) or os.path.isfile(os.path.join(dest_dir, "pyproject.toml")):
                return os.path.abspath(dest_dir)

        if source.startswith("http://") or source.startswith("https://") or source.endswith(".git") or source.startswith("git@"):
            repo_name = source.rstrip("/").split("/")[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            
            # Sanitize repo_name to prevent illegal characters on Windows
            repo_name = re.sub(r"[^a-zA-Z0-9_\-]", "__", repo_name)
            
            target_dest = os.path.abspath(dest_dir or os.path.join(".", "target_repos", repo_name))

            if os.path.isdir(target_dest) and os.path.isdir(os.path.join(target_dest, ".git")):
                active_origin = self._get_remote_origin(target_dest)
                if active_origin and self._normalize_git_url(active_origin) == self._normalize_git_url(source):
                    return target_dest
                else:
                    shutil.rmtree(target_dest, ignore_errors=True)

            os.makedirs(os.path.dirname(target_dest), exist_ok=True)
            try:
                subprocess.run(["git", "clone", source, target_dest], check=True, capture_output=True, text=True, errors="replace")
                return target_dest
            except subprocess.CalledProcessError as exc:
                # Handle bytes vs str in CalledProcessError stderr
                err_msg = exc.stderr.decode(errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                raise RepositoryError(f"Failed to clone repository {source}: {err_msg}") from exc

        local_path = os.path.abspath(source)
        if not os.path.isdir(local_path):
            raise RepositoryError(f"Specified local repository directory does not exist: {local_path}")

        self.ensure_git_baseline(local_path)
        return local_path

    def _get_remote_origin(self, repo_path: str) -> Optional[str]:
        try:
            res = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                errors="replace",
                check=True,
            )
            return res.stdout.strip()
        except Exception:
            return None

    def _normalize_git_url(self, url: str) -> str:
        clean = url.strip().rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        return clean.lower()

    def ensure_git_baseline(self, repo_path: str) -> None:
        """
        Ensure a local directory is a git repo with a clean baseline commit.
        """
        git_dir = os.path.join(repo_path, ".git")
        if os.path.isdir(git_dir):
            return

        try:
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            # Set dummy local credentials so git commit works even if git is unconfigured globally
            subprocess.run(["git", "config", "user.name", "NERO Agent"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "nero@agent.local"], cwd=repo_path, check=True, capture_output=True)
            
            subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "NERO Baseline Commit"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            raise RepositoryError(
                f"Failed to create git baseline in {repo_path}: {stderr.strip()}"
            ) from exc

    def get_diff(self, repo_path: str) -> str:
        """Retrieves active git diff including untracked files."""
        try:
            subprocess.run(["git", "add", "-N", "."], cwd=repo_path, check=False, capture_output=True)
            res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                errors="replace",
            )
            out = res.stdout.strip()
            return out if out else "(no changes)"
        except Exception as exc:
            return f"ERROR generating git diff: {exc}"

    def get_changed_files(self, repo_path: str) -> List[str]:
        """Returns list of modified/added file paths."""
        try:
            subprocess.run(["git", "add", "-N", "."], cwd=repo_path, check=False, capture_output=True)
            res = subprocess.run(
                ["git", "diff", "--name-status", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                errors="replace",
            )
            if not res.stdout.strip():
                return []
            files = []
            for line in res.stdout.strip().splitlines():
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1])
            return files
        except Exception:
            return []
