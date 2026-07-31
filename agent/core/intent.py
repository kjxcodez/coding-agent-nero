"""
Intent classification for NERO.
Determines user intent deterministically without LLM calls.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Intent(str, Enum):
    """
    Exhaustive set of recognised user intent categories.
    """
    STATUS       = "status"        # /status, working memory, session info
    HELP         = "help"          # /help, what commands
    DIFF         = "diff"          # show diff, what changed
    UNDO         = "undo"          # revert, reset, undo
    ARCHITECTURE = "architecture"  # /architecture, component graph, detailed arch view
    RESUME       = "resume"        # /resume, continue the plan, pick up where we left off
    CONTEXT      = "context"       # show context, architecture overview
    ROUTES       = "routes"        # show routes, list API endpoints
    SYMBOLS      = "symbols"       # where is X defined, find function
    SEARCH       = "search"        # find all X, grep, search for
    EXPLAIN      = "explain"       # explain how X works, what does X do
    MODIFY       = "modify"        # add, implement, fix, create, refactor
    VERIFY       = "verify"        # run tests, verify, check build
    REVIEW       = "review"        # review my changes, audit diff
    GIT          = "git"           # commit, branch, merge, push, pull
    REPOSITORY   = "repository"    # clone, switch repo
    CONVERSATION = "conversation"  # general Q&A, default fallback


# Intent → tool name whitelist
INTENT_TOOL_SETS: Dict[Intent, Optional[List[str]]] = {
    # Inline handlers — no LLM, no tools
    Intent.STATUS:        [],
    Intent.HELP:          [],
    Intent.DIFF:          [],
    Intent.UNDO:          [],
    Intent.ARCHITECTURE:  [],
    Intent.RESUME:        [],
    Intent.CONTEXT:       [],
    Intent.ROUTES:        [],
    Intent.SYMBOLS:       [],

    # LLM + restricted tool sets
    Intent.SEARCH:       ["search_code_content", "search_filenames"],
    Intent.EXPLAIN:      ["read_file", "search_code_content", "search_filenames", "list_files"],
    Intent.VERIFY:       ["run_command", "git_diff", "git_status"],
    Intent.REVIEW:       ["git_diff", "git_status", "read_file"],
    Intent.GIT:          ["git_diff", "git_status", "run_command"],
    Intent.REPOSITORY:   ["clone_repo"],
    Intent.CONVERSATION: ["read_file", "search_code_content"],

    # Full tool set — modification tasks need everything
    Intent.MODIFY: None,
}


_RULES: List[Tuple[re.Pattern, Intent]] = [
    # --- Session commands (exact matches or very specific phrases) --------
    (re.compile(r"^/?(status|memory|working memory|session info)\s*$", re.I), Intent.STATUS),
    (re.compile(r"^/?(help|commands|usage|what can you do)\s*$", re.I),       Intent.HELP),
    (re.compile(r"^/?(diff|show diff|git diff|what changed|show changes)\s*$", re.I), Intent.DIFF),
    (re.compile(r"^/?(undo|revert|reset|undo last edit|roll back)\s*$", re.I),         Intent.UNDO),
    (re.compile(r"^/architecture\s*$", re.I),                                  Intent.ARCHITECTURE),
    (re.compile(r"^/?(architecture overview|component graph|show architecture|architecture map)\s*$", re.I), Intent.ARCHITECTURE),
    (re.compile(r"^/?(resume|continue the plan|continue plan|pick up|resume task)\s*$", re.I), Intent.RESUME),
    (re.compile(r"^/?(context|show context|overview)\s*$", re.I),              Intent.CONTEXT),
    (re.compile(r"^/?(routes|show routes|list routes|list api|endpoints|api endpoints|show api|show endpoints)\s*$", re.I), Intent.ROUTES),
    (re.compile(r"\b(list|show|display|get|fetch)\s+(all\s+)?(api\s+)?(routes|endpoints)\b", re.I), Intent.ROUTES),

    # --- Repository operations -------------------------------------------
    (re.compile(r"\b(clone|git clone)\b", re.I),                              Intent.REPOSITORY),
    (re.compile(r"^/repo\b", re.I),                                           Intent.REPOSITORY),
    (re.compile(r"\bswitch (to |the )?(repo|repository|workspace|project)\b", re.I), Intent.REPOSITORY),
    (re.compile(r"\bswitch to (the )?(repo|repository|workspace|project|folder|directory)\b", re.I), Intent.REPOSITORY),
    (re.compile(r"\b(open|load|use|set|bind) (the )?(repo|repository|workspace|project)\b", re.I), Intent.REPOSITORY),

    # --- Git operations --------------------------------------------------
    (re.compile(r"\b(git commit|git push|git pull|git merge|git rebase|git reset|git stash)\b", re.I), Intent.GIT),
    (re.compile(r"\bcommit (the |my |all )?(changes|edits|modifications|files)\b", re.I), Intent.GIT),
    (re.compile(r"\b(create|checkout|switch to|delete) (a |the )?branch\b", re.I), Intent.GIT),
    (re.compile(r"\bpush (to|the)? (remote|origin|upstream)\b", re.I),       Intent.GIT),
    (re.compile(r"\bgit (log|blame|show|tag|fetch)\b", re.I),                Intent.GIT),

    # --- Verification / test -------------------------------------------
    (re.compile(r"\b(run|execute) (the )?(tests?|specs?|unit tests?|integration tests?|test suite)\b", re.I), Intent.VERIFY),
    (re.compile(r"\b(run|start|execute|launch|boot) (the )?(server|app|application|service|script|command|binary|executable)\b", re.I), Intent.VERIFY),
    (re.compile(r"\b(verify|validate|check) (the )?(build|code|implementation|changes)\b", re.I), Intent.VERIFY),
    (re.compile(r"\bnpm test\b|\bpytest\b|\bmocha\b|\bjest\b|\bvitest\b", re.I), Intent.VERIFY),
    (re.compile(r"\bdoes (the )?(build|code|app|project) (compile|work|pass|run)\b", re.I), Intent.VERIFY),

    # --- Review / audit -------------------------------------------------
    (re.compile(r"\b(review|audit|inspect) (my |the )?(changes|edits|diff|modifications|code)\b", re.I), Intent.REVIEW),
    (re.compile(r"\bcode review\b", re.I),                                    Intent.REVIEW),
    (re.compile(r"\bis (my |the )?(implementation|code|change|solution) (correct|right|good)\b", re.I), Intent.REVIEW),

    # --- Symbol lookup -------------------------------------------------
    (re.compile(r"\bwhere (is|are|was|can i find)\b.{1,60}\b(defined|declared|implemented|located)\b", re.I), Intent.SYMBOLS),
    (re.compile(r"\b(find|locate|show) (the )?(definition|declaration|implementation) of\b", re.I), Intent.SYMBOLS),
    (re.compile(r"\bwhat (file|module|class|function|method) (defines?|contains?|has)\b", re.I), Intent.SYMBOLS),
    (re.compile(r"^/symbols?\b", re.I),                                       Intent.SYMBOLS),

    # --- Search --------------------------------------------------------
    (re.compile(r"\b(search|grep|find all|look for|scan for|list all)\b.*(uses?|calls?|references?|occurrences?|instances?)\b", re.I), Intent.SEARCH),
    (re.compile(r"\bwhere (is|are).{1,50}(used|called|referenced|imported)\b", re.I), Intent.SEARCH),
    (re.compile(r"\bsearch (the |for |in )?(codebase|repo|files?|code)\b", re.I), Intent.SEARCH),
    (re.compile(r"\bfind all (uses?|calls?|occurrences?|references?)\b", re.I), Intent.SEARCH),

    # --- Explanation ---------------------------------------------------
    (re.compile(r"\b(explain|describe|walk me through|walk through|break down)\b.*(how|what|why)\b", re.I), Intent.EXPLAIN),
    (re.compile(r"\bhow (does|do|is|are|should)\b.{1,60}\b(work|function|operate|behave)\b", re.I), Intent.EXPLAIN),
    (re.compile(r"\bwhat (does|do|is|are)\b.{1,60}\b(do|mean|represent|return|contain)\b", re.I), Intent.EXPLAIN),
    (re.compile(r"\bcan you explain\b", re.I),                                Intent.EXPLAIN),
    (re.compile(r"\btell me (about|how|what|why)\b", re.I),                   Intent.EXPLAIN),
    (re.compile(r"\bunderstand\b.{0,40}\b(code|function|class|module|file|logic|flow)\b", re.I), Intent.EXPLAIN),
    (re.compile(r"\bshow me how\b", re.I),                                    Intent.EXPLAIN),

    # --- Modification (strong signals — must come BEFORE explain) ------
    (re.compile(r"\b(improve|enhance|optimize)\b.*(application|codebase|feature|logic|performance|function|class|method|module|component|route|endpoint|schema|model|code)\b", re.I), Intent.MODIFY),
    (re.compile(r"\b(add|implement|create|build|write|generate|scaffold)\b.*(feature|endpoint|route|function|class|method|module|component|page|api|service|model|schema|test|migration)\b", re.I), Intent.MODIFY),
    (re.compile(r"\b(fix|debug|resolve|patch|repair|correct)\b.*(bug|error|issue|problem|crash|exception|warning|failure)\b", re.I), Intent.MODIFY),
    (re.compile(r"\b(refactor|restructure|reorganize|rewrite|migrate|update|upgrade|change|rename|move|delete|remove)\b.{1,60}\b(file|function|class|method|module|component|route|endpoint|schema|model|code|logic)\b", re.I), Intent.MODIFY),
    (re.compile(r"\b(add|update|change|modify|edit|replace|remove)\b.{1,40}\b(field|property|attribute|column|parameter|argument|variable|constant|import|dependency)\b", re.I), Intent.MODIFY),
    (re.compile(r"\b(make|set|enable|disable|configure|set up|turn on|turn off)\b.{1,60}\b(work|works|working|function|functions|available|optional|required|default)\b", re.I), Intent.MODIFY),
    (re.compile(r"\bplease\b.{0,30}\b(add|create|fix|implement|update|change|modify|refactor|build|write)\b", re.I), Intent.MODIFY),

    # --- General modification fallback ---------------------------------
    (re.compile(r"^(add|create|implement|fix|build|write|generate|update|change|modify|refactor|delete|remove|rename|improve|enhance)\b", re.I), Intent.MODIFY),
]


class IntentRouter:
    """Classifies user text into an Intent using ordered pattern rules."""

    def classify(self, text: str) -> Intent:
        text = text.strip()
        if not text:
            return Intent.CONVERSATION

        for pattern, intent in _RULES:
            if pattern.search(text):
                return intent

        return Intent.CONVERSATION

    def get_tool_names(self, intent: Intent) -> Optional[List[str]]:
        return INTENT_TOOL_SETS.get(intent)

    def is_inline(self, intent: Intent) -> bool:
        tools = INTENT_TOOL_SETS.get(intent)
        return tools is not None and len(tools) == 0

    def describe(self, text: str) -> str:
        intent = self.classify(text)
        tools = self.get_tool_names(intent)
        if tools is None:
            tool_desc = "all tools"
        elif len(tools) == 0:
            tool_desc = "inline (no LLM)"
        else:
            tool_desc = f"{len(tools)} tool(s): {', '.join(tools)}"
        return f"Intent: {intent.value}  →  {tool_desc}"
