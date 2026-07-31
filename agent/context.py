"""
WorkingMemory backward-compatibility shim.
"""

from .memory.session import ConversationTurn, SessionMemory

WorkingMemory = SessionMemory

__all__ = ["WorkingMemory", "SessionMemory", "ConversationTurn"]
