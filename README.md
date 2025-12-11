# Slack Summary Bot

This bot summarizes Slack threads using Google Gemini when a specific reaction (emoji) is added to a message.

## Prerequisites

*   **Google Cloud Platform Project** with Gemini API enabled.
*   **Slack Workspace** and permissions to create apps.

## Setup

### 1. Slack App Configuration

1.  Go to [Slack API Apps](https://api.slack.com/apps) and create a new app "From an app manifest".
2.  Select your workspace.
3.  Copy the content of `manifest.yaml` from this repository and paste it into the YAML editor.
4.  Create the app.
5.  Install the app to your workspace.
6.  Note down the **Bot User OAuth Token** (`xoxb-...`) and **Signing Secret** (Basic Information > App Credentials).

### 2. Google Cloud Functions Deployment

You can deploy this bot to Google Cloud Functions (2nd Gen) using the gcloud CLI.

1.  Clone this repository.
2.  Set up your environment variables (create a `.env.yaml` file for deployment or set flags):

    *   `SLACK_BOT_TOKEN`: Your Bot User OAuth Token.
    *   `SLACK_SIGNING_SECRET`: Your App Signing Secret.
    *   `GEMINI_API_KEY`: Your Google AI Studio / Vertex AI API Key.
    *   `TARGET_REACTION`: The emoji name to trigger summary (default: `summary-text`).
    *   `GEMINI_MODEL`: The Gemini model to use (default: `gemini-1.5-flash`).

3.  Deploy command:

    ```bash
    gcloud functions deploy slack-summary-bot \
        --gen2 \
        --runtime=python311 \
        --region=YOUR_REGION \
        --source=. \
        --entry-point=summary_bot \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars SLACK_BOT_TOKEN="xoxb-...",SLACK_SIGNING_SECRET="...",GEMINI_API_KEY="...",TARGET_REACTION="summary-text"
    ```

    *Note: `--allow-unauthenticated` is required for Slack to send events to your function URL, but Slack validates requests using the Signing Secret.*

### 3. Finalize Slack Configuration

1.  After deployment, get the **Function URL** (e.g., `https://...run.app`).
2.  Go back to your Slack App settings > **Event Subscriptions**.
3.  Paste the Function URL into the **Request URL** field. It should verify successfully.
4.  Re-install the app if prompted.

## Usage

1.  Add the bot to a channel (or just invite it).
2.  Start a thread.
3.  React to any message in the thread with `:summary-text:` (or your configured emoji).
4.  The bot will fetch the thread, summarize it using Gemini, and post the result as a reply.
