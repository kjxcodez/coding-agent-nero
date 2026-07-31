#!/usr/bin/env python3
"""
NERO Conventional Changelog Generator.
Parses git log commits since the last tag and updates CHANGELOG.md.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

# Define prefix-to-category mapping
CATEGORIES = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "perf": "Performance Improvements",
    "style": "Style & Formatting",
    "test": "Testing",
    "ci": "CI/CD & Infrastructure",
}


def run_command(args, cwd=None):
    try:
        res = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            errors="replace",
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_latest_tag():
    # Find the most recent tag matching v* or similar
    tag = run_command(["git", "describe", "--tags", "--abbrev=0"])
    return tag


def get_commits(since_tag=None):
    cmd = ["git", "log", "--format=%h - %s"]
    if since_tag:
        cmd.append(f"{since_tag}..HEAD")
    output = run_command(cmd)
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def parse_commits(commits):
    grouped = {cat: [] for cat in CATEGORIES.values()}
    grouped["Other Changes"] = []

    # Conventional commit regex: prefix(scope)?: message
    commit_re = re.compile(r"^([a-z0-9]+) - ([a-z0-9]+)(?:\(([^)]+)\))?:\s*(.*)$", re.I)

    for c in commits:
        match = commit_re.match(c)
        if match:
            commit_hash, prefix, scope, message = match.groups()
            prefix_lower = prefix.lower()
            category = CATEGORIES.get(prefix_lower)
            
            scope_str = f"**{scope}**: " if scope else ""
            formatted = f"- {scope_str}{message} ({commit_hash})"

            if category:
                grouped[category].append(formatted)
            else:
                grouped["Other Changes"].append(f"- {prefix}{f'({scope})' if scope else ''}: {message} ({commit_hash})")
        else:
            # Fallback for non-conventional commits
            parts = c.split(" - ", 1)
            if len(parts) == 2:
                commit_hash, msg = parts
                grouped["Other Changes"].append(f"- {msg} ({commit_hash})")
            else:
                grouped["Other Changes"].append(f"- {c}")

    # Remove empty categories
    return {k: v for k, v in grouped.items() if v}


def generate_markdown(version, parsed_commits):
    date_str = datetime.date.today().isoformat()
    lines = [f"## [{version}] - {date_str}", ""]
    
    for category, items in parsed_commits.items():
        lines.append(f"### {category}")
        lines.append("")
        for item in items:
            lines.append(item)
        lines.append("")
        
    return "\n".join(lines)


def update_changelog_file(changelog_path, new_content):
    header = "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n"
    
    if os.path.exists(changelog_path):
        with open(changelog_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Strip header if it already exists to avoid duplication
        if content.startswith("# Changelog"):
            # Find the end of the header
            body_start = content.find("## ")
            if body_start != -1:
                content = content[body_start:]
            else:
                content = ""
        
        updated_content = header + new_content + "\n" + content
    else:
        updated_content = header + new_content

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(updated_content)


def main():
    parser = argparse.ArgumentParser(description="Generate CHANGELOG update from conventional commits.")
    parser.add_argument("--release-version", required=True, help="Version to release (e.g. v1.0.1)")
    parser.add_argument("--dry-run", action="store_true", help="Print changelog instead of writing to file")
    parser.add_argument("--changelog-path", default="CHANGELOG.md", help="Path to CHANGELOG.md")
    parser.add_argument("--release-notes-path", help="Path to write only the new release notes section")
    args = parser.parse_args()

    latest_tag = get_latest_tag()
    print(f"Latest tag found: {latest_tag or 'None (parsing entire history)'}")
    
    commits = get_commits(latest_tag)
    if not commits:
        print("No commits found since the last tag. Nothing to do.")
        sys.exit(0)
        
    print(f"Found {len(commits)} commits to process.")
    parsed = parse_commits(commits)
    
    version = args.release_version
    if not version.startswith("v"):
        version = "v" + version
        
    markdown_content = generate_markdown(version, parsed)
    
    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(markdown_content)
        print("----------------------")
    else:
        update_changelog_file(args.changelog_path, markdown_content)
        print(f"Changelog updated successfully at: {os.path.abspath(args.changelog_path)}")
        
        if args.release_notes_path:
            with open(args.release_notes_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            print(f"Release notes written successfully at: {os.path.abspath(args.release_notes_path)}")


if __name__ == "__main__":
    main()
