"""
Unit tests for the Slack Summary Bot (No-Bolt Version).

This file contains tests to verify:
1. Conversation formatting.
2. Gemini API integration (mocked).
3. Request handling logic (Signature, Retries, Events).
4. Reaction processing logic.

Why mock?
We mock external dependencies (Slack API, Gemini API, File I/O) to:
- Ensure tests are fast and deterministic.
- Avoid network calls and authentication requirements.
- Isolate the logic from external system failures.
"""

import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import json
import main

class TestSummaryBot(unittest.TestCase):

    def setUp(self):
        # Mock the WebClient instance in main to verify calls
        self.mock_client = MagicMock()
        main.client = self.mock_client

        # Mock SignatureVerifier to always pass in tests
        self.mock_verifier = MagicMock()
        self.mock_verifier.is_valid_request.return_value = True
        main.signature_verifier = self.mock_verifier

    def test_format_conversation(self):
        """
        Test formatting and user caching.
        """
        # Mock users_info
        self.mock_client.users_info.side_effect = lambda user: {
            "ok": True,
            "user": {"real_name": "Test User"} if user == "U1" else {"real_name": "User 2"}
        }

        messages = [
            {"user": "U1", "text": "Msg 1"},
            {"user": "U1", "text": "Msg 2"},
            {"user": "U2", "text": "Msg 3"}
        ]

        formatted = main.format_conversation(messages)

        self.assertIn("Test User: Msg 1", formatted)
        self.assertIn("Test User: Msg 2", formatted)
        self.assertIn("User 2: Msg 3", formatted)
        self.assertEqual(self.mock_client.users_info.call_count, 2)

    @patch("main.genai.GenerativeModel")
    def test_summarize_text(self, mock_model_class):
        """
        Test Gemini integration.
        """
        mock_instance = mock_model_class.return_value
        mock_instance.generate_content.return_value.text = "Summary"

        main.summarize_text("content")
        mock_instance.generate_content.assert_called()

    @patch("main.summarize_text")
    def test_process_event_reaction(self, mock_summarize):
        """
        Test reaction event processing flow.
        """
        mock_summarize.return_value = "Done"

        # Mock history/replies
        self.mock_client.conversations_history.return_value = {
            "ok": True, "messages": [{"ts": "100", "thread_ts": "100"}]
        }
        self.mock_client.conversations_replies.return_value = {
            "ok": True, "messages": [{"ts": "100", "user": "U1", "text": "Hi"}]
        }

        event = {
            "type": "reaction_added",
            "reaction": "summary-text",
            "item": {"channel": "C1", "ts": "100"}
        }

        main.process_event(event)

        self.mock_client.chat_postMessage.assert_called_with(
            channel="C1", thread_ts="100", text="Done"
        )

    def test_http_url_verification(self):
        """
        Test Slack URL verification challenge.
        """
        mock_req = MagicMock()
        mock_req.get_data.return_value = b""
        mock_req.headers = {}
        mock_req.get_json.return_value = {
            "type": "url_verification",
            "challenge": "challenge_token"
        }

        resp = main.summary_bot(mock_req)
        self.assertEqual(resp, "challenge_token")

    def test_http_retry_ignore(self):
        """
        Test ignoring retries.
        """
        mock_req = MagicMock()
        mock_req.get_data.return_value = b""
        mock_req.headers = {"x-slack-retry-num": "1"}
        mock_req.get_json.return_value = {"type": "event_callback"}

        resp, code = main.summary_bot(mock_req)
        self.assertEqual(code, 200)
        self.assertEqual(resp, "Ignored retry")

    @patch("main.process_event")
    def test_http_event_callback(self, mock_process):
        """
        Test normal event callback.
        """
        mock_req = MagicMock()
        mock_req.get_data.return_value = b""
        mock_req.headers = {}
        mock_req.get_json.return_value = {
            "type": "event_callback",
            "event": {"foo": "bar"}
        }

        resp, code = main.summary_bot(mock_req)
        self.assertEqual(code, 200)
        mock_process.assert_called_with({"foo": "bar"})

if __name__ == "__main__":
    unittest.main()
