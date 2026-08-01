"""
Unit tests for the OpenRouter/free model tool history plain-text conversion logic.
"""

import sys
import unittest

sys.path.insert(0, ".")

from agent.llm.providers import format_tool_messages_as_text


class TestOpenRouterFormat(unittest.TestCase):
    def test_format_tool_messages_as_text_converts_assistant_tool_calls(self):
        """Assistant message with tool calls should be converted to plain text."""
        msgs = [
            {"role": "user", "content": "Initial prompt"},
            {
                "role": "assistant",
                "content": "Thinking...",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "app/models/note.model.js"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "read_file",
                "content": "const mongoose = require('mongoose');",
            },
        ]

        formatted = format_tool_messages_as_text(msgs)

        self.assertEqual(len(formatted), 3)
        self.assertEqual(formatted[0], msgs[0])

        # Assistant message check
        self.assertEqual(formatted[1]["role"], "assistant")
        self.assertNotIn("tool_calls", formatted[1])
        self.assertIn("Thinking...", formatted[1]["content"])
        self.assertIn("Tool Call: read_file", formatted[1]["content"])
        self.assertIn('{"path": "app/models/note.model.js"}', formatted[1]["content"])

        # Tool message check
        self.assertEqual(formatted[2]["role"], "user")
        self.assertNotIn("tool_call_id", formatted[2])
        self.assertIn("Tool 'read_file' returned:", formatted[2]["content"])
        self.assertIn("const mongoose = require('mongoose');", formatted[2]["content"])

    def test_format_tool_messages_as_text_handles_non_tool_messages(self):
        """Conversations without tool calls should remain unchanged."""
        msgs = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]
        formatted = format_tool_messages_as_text(msgs)
        self.assertEqual(formatted, msgs)


if __name__ == "__main__":
    unittest.main()
