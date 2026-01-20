"""
Simple test server to receive and log webhook events from Teams Meeting Recorder.

Usage:
    python webhook_test_server.py

Then set in your .env:
    WEBHOOK_URL=http://localhost:5000/webhook

The server will log all incoming webhooks with formatted JSON output.
"""

from flask import Flask, request, jsonify
import json
from datetime import datetime
from typing import Any

app = Flask(__name__)


def format_webhook_data(data: dict) -> str:
    """Format webhook data for pretty printing."""
    lines = []
    lines.append("=" * 80)
    lines.append("🔔 WEBHOOK RECEIVED")
    lines.append("=" * 80)
    lines.append(f"⏰ Received at: {datetime.now().isoformat()}")
    lines.append("")
    lines.append("📊 Webhook Data:")
    lines.append("-" * 80)

    for key, value in data.items():
        if key == "file_location" and value:
            # Truncate long URLs for display
            display_value = value if len(value) <= 70 else value[:67] + "..."
            lines.append(f"  {key:20} {display_value}")
        else:
            lines.append(f"  {key:20} {value}")

    lines.append("-" * 80)

    # Calculate duration if both timestamps are present
    if "started_at" in data and "stopped_at" in data:
        try:
            start = datetime.fromisoformat(data["started_at"])
            stop = datetime.fromisoformat(data["stopped_at"])
            duration = (stop - start).total_seconds()
            lines.append(f"  {'duration':20} {duration:.2f} seconds")
            lines.append("-" * 80)
        except:
            pass

    lines.append("")
    return "\n".join(lines)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive webhook POST requests."""
    try:
        data = request.get_json()

        if data:
            print(format_webhook_data(data))
            print("✅ Webhook processed successfully\n")
        else:
            print("⚠️  Received empty webhook payload")

        return jsonify({"status": "received", "message": "Webhook processed"}), 200

    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/", methods=["GET"])
def index():
    """Root endpoint with server info."""
    return jsonify({
        "name": "Teams Meeting Recorder - Webhook Test Server",
        "webhook_url": "http://localhost:5000/webhook",
        "status": "running",
        "message": "Set WEBHOOK_URL=http://localhost:5000/webhook in your .env file"
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🚀 Webhook Test Server Starting")
    print("=" * 80)
    print(f"📡 Server URL:      http://localhost:5000")
    print(f"🔗 Webhook URL:     http://localhost:5000/webhook")
    print(f"💚 Health Check:    http://localhost:5000/health")
    print("")
    print("📝 Configuration:")
    print("   Set in your .env file:")
    print("   WEBHOOK_URL=http://localhost:5000/webhook")
    print("")
    print("   Or in docker compose:")
    print("   environment:")
    print("     - WEBHOOK_URL=http://host.docker.internal:5000/webhook")
    print("")
    print("=" * 80 + "\n")

    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
