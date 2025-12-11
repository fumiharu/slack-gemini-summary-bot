import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Set dummy env vars
os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
os.environ["SLACK_SIGNING_SECRET"] = "test-secret"
os.environ["GEMINI_API_KEY"] = "test-api-key"
os.environ["TARGET_REACTION"] = ":summary-text:" # Test with colons

# Helper to mock App decorator
def mock_event_decorator(event_name):
    def decorator(func):
        return func
    return decorator

# Helper for middleware decorator (takes no args usually when used as @app.middleware, but wait...)
# Bolt's @app.middleware is used as:
# @app.middleware  <-- no args
# def func(...)
# So it is the decorator itself.
def mock_middleware_decorator(func):
    return func

# Patch slack_bolt.App
patcher = patch("slack_bolt.App")
MockApp = patcher.start()
mock_app_instance = MockApp.return_value
mock_app_instance.event.side_effect = mock_event_decorator
# Fix: app.middleware is a method that takes the function as argument if used as decorator
mock_app_instance.middleware.side_effect = mock_middleware_decorator

import main

patcher.stop()

class TestSummaryBot(unittest.TestCase):

    def test_format_conversation_with_cache(self):
        mock_client = MagicMock()
        # Mock user info
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
        self.assertIn("Test User: Msg 1", formatted)
        self.assertIn("Test User: Msg 2", formatted)
        self.assertIn("User 2: Msg 3", formatted)

        # users_info should be called only once for U1 and once for U2
        self.assertEqual(mock_client.users_info.call_count, 2)

    @patch("main.genai.GenerativeModel")
    def test_summarize_text(self, mock_model_class):
        mock_model_instance = mock_model_class.return_value
        mock_response = MagicMock()
        mock_response.text = "**サマリー**\nTest Summary"
        mock_model_instance.generate_content.return_value = mock_response

        summary = main.summarize_text("User: text")
        self.assertIn("**サマリー**", summary)

    @patch("main.summarize_text")
    def test_handle_reaction_added_target(self, mock_summarize):
        mock_summarize.return_value = "Summary Result"

        mock_client = MagicMock()
        mock_say = MagicMock()

        # Test with reaction that matches "summary-text" even if event has no colons
        event = {
            "reaction": "summary-text",
            "item": {"channel": "C1", "ts": "100"}
        }

        # Mock history
        mock_client.conversations_history.return_value = {
            "ok": True,
            "messages": [{"ts": "100", "thread_ts": "100"}]
        }

        # Mock replies
        mock_client.conversations_replies.return_value = {
            "ok": True,
            "messages": [{"ts": "100", "user": "U1", "text": "Hello"}]
        }

        main.handle_reaction_added(event, mock_client, mock_say)

        mock_summarize.assert_called()
        mock_client.chat_postMessage.assert_called()

    def test_ignore_retry_middleware(self):
        # We need to test the middleware logic.
        # Since we mocked the middleware decorator to just return the function,
        # 'main.ignore_retry' is the function itself.

        mock_request = MagicMock()
        mock_next = MagicMock()

        # Case 1: Retry header present
        mock_request.headers = {"x-slack-retry-num": "1"}
        response = main.ignore_retry(mock_request, mock_next)

        # Should NOT call next()
        mock_next.assert_not_called()
        # Should return a response
        self.assertIsNotNone(response)
        self.assertEqual(response.status, 200)

        # Case 2: No retry header
        mock_request.headers = {}
        main.ignore_retry(mock_request, mock_next)

        # Should call next()
        mock_next.assert_called()

if __name__ == "__main__":
    unittest.main()
