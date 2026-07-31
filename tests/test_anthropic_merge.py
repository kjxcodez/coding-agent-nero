"""
Unit tests for the Anthropic consecutive same-role message merge logic.
Tests the exact logic inserted into AnthropicProvider.generate() to satisfy
Anthropic's strict user/assistant alternation requirement.
"""

import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, ".")


def _merge_consecutive(anthropic_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Replication of the merge logic in AnthropicProvider.generate() for isolated testing.
    Merges consecutive same-role messages whose content is a list.
    """
    merged: List[Dict[str, Any]] = []
    for msg in anthropic_messages:
        if (
            merged
            and merged[-1]["role"] == msg["role"]
            and isinstance(merged[-1]["content"], list)
            and isinstance(msg["content"], list)
        ):
            merged[-1]["content"].extend(msg["content"])
        else:
            merged.append({"role": msg["role"], "content": msg["content"]})
    return merged


class TestAnthropicMergeLogic(unittest.TestCase):
    def test_two_consecutive_tool_results_merged(self):
        """Two consecutive tool results (role=user) must be merged into one user message."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "id1", "name": "read_file", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id1", "content": "result1"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id2", "content": "result2"}]},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 3, "Expected 3 messages after merge")
        self.assertEqual(result[2]["role"], "user")
        self.assertEqual(len(result[2]["content"]), 2, "Both tool_result blocks should be merged into one message")

    def test_single_tool_result_unchanged(self):
        """A single tool result should not be merged with anything."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "id1", "name": "read_file", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id1", "content": "result1"}]},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 3)

    def test_string_content_user_not_merged_with_list_content_user(self):
        """String-content user msg must not be merged with a list-content (tool_result) user msg."""
        msgs = [
            {"role": "user", "content": "some text"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id1", "content": "result"}]},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 2, "String and list content user messages must not be merged")

    def test_three_consecutive_tool_results_merged_into_one(self):
        """Three consecutive tool results must all merge into a single user message."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "tool_use"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id1", "content": "r1"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id2", "content": "r2"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "id3", "content": "r3"}]},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 3)
        self.assertEqual(
            len(result[2]["content"]), 3, "All three tool_result blocks must be in the single merged user message"
        )

    def test_alternating_roles_unchanged(self):
        """Properly alternating messages should pass through the merge step unchanged."""
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Continue"},
            {"role": "assistant", "content": "Done"},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 4)

    def test_empty_messages_handled(self):
        """Empty input should return empty output."""
        result = _merge_consecutive([])
        self.assertEqual(result, [])

    def test_merge_preserves_content_order(self):
        """Merged content blocks must appear in original order."""
        block1 = {"type": "tool_result", "tool_use_id": "id1", "content": "first"}
        block2 = {"type": "tool_result", "tool_use_id": "id2", "content": "second"}
        msgs = [
            {"role": "user", "content": [block1]},
            {"role": "user", "content": [block2]},
        ]
        result = _merge_consecutive(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"][0]["tool_use_id"], "id1")
        self.assertEqual(result[0]["content"][1]["tool_use_id"], "id2")


if __name__ == "__main__":
    unittest.main()
