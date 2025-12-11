import os
import logging
import json
import functions_framework
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from slack_sdk.errors import SlackApiError
import google.generativeai as genai

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack components
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")

# We can initialize client lazily or here.
# WebClient does NOT depend on sqlite3.
client = WebClient(token=SLACK_BOT_TOKEN)
signature_verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# Initialize Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not set.")

# Configuration
TARGET_REACTION = os.environ.get("TARGET_REACTION", "summary-text").strip(":")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Load prompt from file
PROMPT_TEMPLATE = ""
try:
    with open(os.path.join(os.path.dirname(__file__), "prompt.txt"), "r", encoding="utf-8") as f:
        PROMPT_TEMPLATE = f.read()
except Exception as e:
    logger.error(f"Error reading prompt.txt: {e}")
    PROMPT_TEMPLATE = "要約してください：\n\n"

def get_user_name(user_id, user_cache):
    if user_id in user_cache:
        return user_cache[user_id]

    try:
        response = client.users_info(user=user_id)
        if response["ok"]:
            user = response["user"]
            name = user.get("real_name") or user.get("name")
            user_cache[user_id] = name
            return name
    except Exception as e:
        logger.error(f"Error fetching user info for {user_id}: {e}")

    return user_id

def format_conversation(messages):
    formatted_text = ""
    user_cache = {} # Local cache for this request

    for msg in messages:
        user_id = msg.get("user")
        text = msg.get("text", "")
        if user_id:
            user_name = get_user_name(user_id, user_cache)
            formatted_text += f"{user_name}: {text}\n"
        else:
            formatted_text += f"System/Bot: {text}\n"
    return formatted_text

def summarize_text(text):
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        prompt = f"{PROMPT_TEMPLATE}{text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return "申し訳ありません。要約の生成中にエラーが発生しました。"

def process_event(event):
    type = event.get("type")

    if type == "reaction_added":
        handle_reaction_added(event)

def handle_reaction_added(event):
    reaction = event.get("reaction")

    # Robust check: strip colons
    if reaction.strip(":") != TARGET_REACTION:
        return

    item = event.get("item")
    channel_id = item.get("channel")
    ts = item.get("ts")

    logger.info(f"Received reaction '{reaction}' on message {ts} in channel {channel_id}")

    try:
        # Fetch the message to check for thread_ts
        history_response = client.conversations_history(
            channel=channel_id,
            latest=ts,
            limit=1,
            inclusive=True
        )

        messages = history_response.get("messages", [])
        if not messages:
            logger.error("Message not found.")
            return

        target_message = messages[0]
        thread_ts = target_message.get("thread_ts")

        parent_ts = thread_ts if thread_ts else ts

        # Now fetch all replies
        replies_response = client.conversations_replies(
            channel=channel_id,
            ts=parent_ts
        )

        thread_messages = replies_response.get("messages", [])

        if not thread_messages:
            logger.info("No messages found in thread.")
            return

        # Format conversation
        conversation_text = format_conversation(thread_messages)

        # Summarize
        summary = summarize_text(conversation_text)

        # Reply to thread
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=parent_ts,
            text=summary
        )

    except Exception as e:
        logger.error(f"Error handling reaction: {e}")

@functions_framework.http
def summary_bot(request):
    """
    HTTP Cloud Function entry point.
    """
    # 1. Verify Request Signature
    if not signature_verifier.is_valid_request(request.get_data(), request.headers):
        logger.warning("Invalid request signature")
        return "Invalid signature", 403

    # 2. Parse Body
    try:
        body = request.get_json()
    except Exception:
        return "Bad Request", 400

    # 3. Handle URL Verification (for Slack App setup)
    if body.get("type") == "url_verification":
        return body.get("challenge")

    # 4. Handle Retries
    # Slack sends 'x-slack-retry-num' header on retries.
    # We ignore them to avoid duplicate processing.
    if "x-slack-retry-num" in request.headers:
        logger.info(f"Ignoring retry request: {request.headers.get('x-slack-retry-num')}")
        return "Ignored retry", 200

    # 5. Handle Events
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        # Process in background?
        # For simplicity and GCF Gen2 (which handles concurrency better),
        # we process synchronously but rely on 200 OK being final.
        # Note: Slack expects 200 OK within 3s. If logic is slow,
        # we might need to push to Pub/Sub or return 200 first.
        # But user wants a simple summary bot.
        # If we just return 200 and process, GCF might kill the process?
        # GCF Gen 2 keeps running until response is sent.
        # If we wait for Gemini, we might timeout Slack's 3s.
        # But we handle retries, so the first timeout is "fine" provided we eventually finish.
        # The retry handler above prevents the SECOND execution.
        # The FIRST execution continues to run even if Slack gives up waiting for the 200 OK.
        # (This depends on GCF behavior: usually it keeps running until function timeout).

        process_event(event)
        return "OK", 200

    return "Not Found", 404
