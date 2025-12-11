"""
Unit tests for the Slack Summary Bot.

This file contains tests to verify:
1. Conversation formatting and user name caching.
2. Gemini API integration (mocked).
3. Logic for handling reaction events and thread retrieval.
4. Middleware for handling Slack retries.

Why mock?
We mock external dependencies (Slack API, Gemini API, File I/O) to:
- Ensure tests are fast and deterministic.
- Avoid network calls and authentication requirements during testing.
- Isolate the logic of our bot from external system failures.
"""

import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys

# Set dummy env vars for testing purposes
os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
os.environ["SLACK_SIGNING_SECRET"] = "test-secret"
os.environ["GEMINI_API_KEY"] = "test-api-key"
os.environ["TARGET_REACTION"] = ":summary-text:" # Test with colons to verify stripping logic

# --- Patching Strategy ---
# We need to patch `slack_bolt.App` before importing `main`.
# This prevents the real `App` from initializing, which attempts to call `auth.test`
# and requires valid credentials.

# Helper to mock Bolt's event decorator
def mock_event_decorator(event_name):
    def decorator(func):
        return func
    return decorator

# Helper to mock Bolt's middleware decorator
def mock_middleware_decorator(func):
    return func

# Apply the patch
patcher = patch("slack_bolt.App")
MockApp = patcher.start()
mock_app_instance = MockApp.return_value
# Mock the decorators to return the original function, so we can test the logic directly
mock_app_instance.event.side_effect = mock_event_decorator
mock_app_instance.middleware.side_effect = mock_middleware_decorator

# Import the module under test
import main

# Stop the patcher
patcher.stop()

class TestSummaryBot(unittest.TestCase):

    def test_format_conversation_with_cache(self):
        """
        Test that `format_conversation` correctly formats messages and caches user names.

        Why:
        - To verify that user IDs are replaced with real names.
        - To ensure `users_info` is not called redundantly for the same user (performance optimization).
        """
        mock_client = MagicMock()
        # Mock user info response
        mock_client.users_info.side_effect = lambda user: {
            "ok": True,
            "user": {"real_name": "Test User"} if user == "U1" else {"real_name": "User 2"}
        }

        messages = [
            {"user": "U1", "text": "Msg 1"},
            {"user": "U1", "text": "Msg 2"}, # Should use cache
            {"user": "U2", "text": "Msg 3"}
        ]

        formatted = main.format_conversation(messages, mock_client)

        # Check formatting
        self.assertIn("Test User: Msg 1", formatted)
        self.assertIn("Test User: Msg 2", formatted)
        self.assertIn("User 2: Msg 3", formatted)

        # Check caching behavior: users_info should be called only once for U1 and once for U2
        self.assertEqual(mock_client.users_info.call_count, 2)

    @patch("main.genai.GenerativeModel")
    def test_summarize_text(self, mock_model_class):
        """
        Test that `summarize_text` calls the Gemini API with the correct prompt.

        Why:
        - To verify that the prompt template is correctly prepended to the text.
        - To ensure the Gemini client is initialized and called correctly.
        """
        mock_model_instance = mock_model_class.return_value
        mock_response = MagicMock()
        mock_response.text = "**サマリー**\nTest Summary"
        mock_model_instance.generate_content.return_value = mock_response

        # Set a known prompt template in main for this test
        original_template = main.PROMPT_TEMPLATE
        main.PROMPT_TEMPLATE = "TEMPLATE:"

        try:
            summary = main.summarize_text("User: text")

            # Verify the call arguments
            mock_model_instance.generate_content.assert_called_with("TEMPLATE:User: text")
            self.assertIn("**サマリー**", summary)
        finally:
            main.PROMPT_TEMPLATE = original_template

    @patch("main.summarize_text")
    def test_handle_reaction_added_target(self, mock_summarize):
        """
        Test the main event flow when the target reaction is added.

        Why:
        - To verify that the bot fetches the thread, calls the summarizer, and posts the result.
        - To ensure correct API methods (`conversations_history`, `conversations_replies`) are used.
        """
        mock_summarize.return_value = "Summary Result"

        mock_client = MagicMock()
        mock_say = MagicMock()

        # Test with reaction that matches "summary-text" (without colons)
        # validating that the bot logic handles normalizing reaction names.
        event = {
            "reaction": "summary-text",
            "item": {"channel": "C1", "ts": "100"}
        }

        # Mock history response (finding the parent thread_ts)
        mock_client.conversations_history.return_value = {
            "ok": True,
            "messages": [{"ts": "100", "thread_ts": "100"}]
        }

        # Mock replies response (fetching the full thread)
        mock_client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100", "user": "U1", "text": "Hello"}]
        }

        main.handle_reaction_added(event, mock_client, mock_say)

        # Assertions
        mock_summarize.assert_called()
        mock_client.chat_postMessage.assert_called_with(
            channel="C1",
            thread_ts="100",
            text="Summary Result"
        )

    def test_ignore_retry_middleware(self):
        """
        Test the middleware that filters out Slack retry requests.

        Why:
        - Serverless functions (like GCF) may take longer than 3 seconds to respond.
        - Slack retries requests if no response is received in 3s.
        - We need to ignore these retries to prevent duplicate processing/posting.
        """
        mock_request = MagicMock()
        mock_next = MagicMock()

        # Case 1: Retry header present -> Should Stop
        mock_request.headers = {"x-slack-retry-num": "1"}
        response = main.ignore_retry(mock_request, mock_next)

        # Verify execution stopped (next() NOT called) and 200 OK returned
        mock_next.assert_not_called()
        self.assertIsNotNone(response)
        self.assertEqual(response.status, 200)

        # Case 2: No retry header -> Should Continue
        mock_request.headers = {}
        main.ignore_retry(mock_request, mock_next)

        # Verify execution continued
        mock_next.assert_called()

if __name__ == "__main__":
    unittest.main()
