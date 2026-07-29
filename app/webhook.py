"""Webhook notification system for recording completion."""

import logging
import asyncio
import json
from typing import Optional
from datetime import datetime
import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class WebhookPayload:
    """Payload to send to webhook when recording completes."""

    def __init__(
        self,
        session_id: str,
        meeting_url: str,
        file_location: str,
        started_at: datetime,
        stopped_at: datetime
    ):
        """
        Initialize webhook payload.

        Args:
            session_id: Unique session identifier
            meeting_url: Teams meeting URL
            file_location: Local path, MinIO URL, or Azure blob path/URL
            started_at: When recording started
            stopped_at: When recording stopped
        """
        self.session_id = session_id
        self.meeting_url = meeting_url
        self.file_location = file_location
        self.started_at = started_at
        self.stopped_at = stopped_at

    def to_dict(self) -> dict:
        """Convert payload to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "meeting_url": self.meeting_url,
            "file_location": self.file_location,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None
        }


async def send_webhook(webhook_url: str, payload: WebhookPayload) -> bool:
    """
    Send webhook notification asynchronously.

    Args:
        webhook_url: URL to send the webhook to
        payload: WebhookPayload instance to send

    Returns:
        True if webhook was sent successfully, False otherwise
    """
    if not webhook_url:
        logger.debug("Webhook URL not configured, skipping notification")
        return False

    try:
        logger.info(f"Sending webhook notification to: {webhook_url}")

        headers = {"Content-Type": "application/json"}
        if settings.webhook_secret:
            headers["X-Webhook-Secret"] = settings.webhook_secret

        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload.to_dict(),
                timeout=aiohttp.ClientTimeout(total=30),
                headers=headers
            ) as response:
                if response.status in (200, 201, 202, 204):
                    logger.info(f"Webhook sent successfully (status: {response.status})")
                    return True
                else:
                    logger.warning(f"Webhook returned status {response.status}")
                    try:
                        response_text = await response.text()
                        logger.warning(f"Webhook response: {response_text}")
                    except Exception as e:
                        logger.warning(f"Could not read webhook response body: {e}")
                    return False

    except asyncio.TimeoutError:
        logger.error(f"Webhook request timed out to: {webhook_url}")
        return False
    except Exception as e:
        logger.error(f"Failed to send webhook to {webhook_url}: {e}")
        return False
