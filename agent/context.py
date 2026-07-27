"""
WorkingMemory backward-compatibility shim.
"""

from .memory.session import SessionMemory, ConversationTurn

WorkingMemory = SessionMemory

__all__ = ["WorkingMemory", "SessionMemory", "ConversationTurn"]
