# Webhooks

Set `WEBHOOK_URL` and the bot POSTs JSON when a session ends: on success, and on failure with an empty `file_location`.

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "reference": "order-4711",
  "file_location": "meeting-recordings/550e8400-.../550e8400-..._20250121_143022.flac",
  "started_at": "2025-01-21T14:30:22.123456",
  "stopped_at": "2025-01-21T14:35:45.654321"
}
```

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Session identifier (UUID) |
| `meeting_url` | string | The meeting that was joined |
| `reference` | string or null | The caller's reference from `/join`, `null` when none was given |
| `file_location` | string | Local path, blob path or object URL; `.wav` or `.flac` per `RECORDING_FORMAT`. Empty when the recording failed |
| `started_at` | ISO 8601 | When the session started |
| `stopped_at` | ISO 8601 | When the session stopped |

The POST has a 30 second timeout; 200, 201, 202 and 204 count as delivered. A failed webhook is logged and does not fail the recording. Set `WEBHOOK_SECRET` to have it sent as the `X-Webhook-Secret` header.
