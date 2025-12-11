import os
import logging
import slack_bolt
from slack_bolt.adapter.google_cloud_functions import SlackRequestHandler
import google.generativeai as genai

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack App
app = slack_bolt.App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    process_before_response=True,
)

# Initialize Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not set.")

# Configuration
# Strip colons just in case user configures it as :emoji:
TARGET_REACTION = os.environ.get("TARGET_REACTION", "summary-text").strip(":")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Load prompt from file
PROMPT_TEMPLATE = ""
try:
    with open(os.path.join(os.path.dirname(__file__), "prompt.txt"), "r", encoding="utf-8") as f:
        PROMPT_TEMPLATE = f.read()
except Exception as e:
    logger.error(f"Error reading prompt.txt: {e}")
    PROMPT_TEMPLATE = "要約してください：\n\n" # Fallback

@app.middleware
def ignore_retry(request, next):
    if "x-slack-retry-num" in request.headers:
        logger.info(f"Ignoring retry request: {request.headers.get('x-slack-retry-num')}")
        return slack_bolt.BoltResponse(status=200, body="Ignored retry")
    next()

def get_user_name(user_id, client, user_cache):
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

def format_conversation(messages, client):
    formatted_text = ""
    user_cache = {} # Local cache for this request

    for msg in messages:
        user_id = msg.get("user")
        text = msg.get("text", "")
        if user_id:
            user_name = get_user_name(user_id, client, user_cache)
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

@app.event("reaction_added")
def handle_reaction_added(event, client, say):
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

        # Determine the parent thread timestamp
        # If thread_ts is missing, the message itself is the start of a potential thread
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
        conversation_text = format_conversation(thread_messages, client)

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

handler = SlackRequestHandler(app)

def summary_bot(request):
    return handler.handle(request)
