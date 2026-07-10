"""
WhatsApp adapter (item #9) via Twilio's WhatsApp API -- the simplest way to
get a real WhatsApp bot running without going through Meta's full Business
API approval process. Twilio has a free sandbox for development.

Setup:
    1. pip install twilio flask
    2. Create a free Twilio account, join their WhatsApp sandbox
       (https://www.twilio.com/docs/whatsapp/sandbox), and note your
       Account SID, Auth Token, and sandbox WhatsApp number.
    3. Put them in your .env (see .env.example):
       TWILIO_ACCOUNT_SID=...
       TWILIO_AUTH_TOKEN=...
       TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
    4. Run this file, then expose it publicly (e.g. `ngrok http 5001`) and
       set that URL as the sandbox's "when a message comes in" webhook.

Usage:
    python integrations/whatsapp_bot.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

from assistant.core_assistant import StockAssistant

app = Flask(__name__)
bot = StockAssistant()


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_text = request.values.get("Body", "").strip()
    sender = request.values.get("From", "unknown")  # e.g. "whatsapp:+1415..."
    user_id = f"whatsapp-{sender}"

    result = bot.handle_message(user_id, incoming_text)

    twiml = MessagingResponse()
    msg = twiml.message(result["text"][:1500])  # WhatsApp message length limit

    if result.get("image_path") or result.get("chart") is not None:
        os.makedirs("static", exist_ok=True)
        fname = f"chart_{abs(hash(user_id))}.png"
        path = os.path.join("static", fname)
        try:
            if result.get("image_path"):
                # Preferred: matplotlib PNG already generated alongside the
                # forecast -- just copy it into the served static folder.
                import shutil
                shutil.copyfile(result["image_path"], path)
            else:
                result["chart"].write_image(path)  # requires `kaleido`
            base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
            if base_url:
                msg.media(f"{base_url}/static/{fname}")
        except Exception:
            pass  # image export optional; text reply still sends

    return str(twiml)


if __name__ == "__main__":
    app.run(port=5001, debug=True)
