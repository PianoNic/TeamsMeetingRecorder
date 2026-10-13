# Webhooks

Set `WEBHOOK_URL` and the bot POSTs JSON when a session ends, whatever the outcome. With `WEBHOOK_EVENTS=true` it also POSTs every status change while the session runs.

```json
{
  "event": "finished",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "reference": "order-4711",
  "status": "stopped",
  "error_message": null,
  "file_location": "meeting-recordings/550e8400-.../550e8400-..._20250121_143022.flac",
  "started_at": "2025-01-21T14:30:22.123456",
  "stopped_at": "2025-01-21T14:35:45.654321",
  "sequence": 4,
  "occurred_at": "2025-01-21T14:35:46.001234"
}
```

| Field | Type | Description |
|---|---|---|
| `event` | string | `finished` when the session is over, `status` for a change while it runs (`WEBHOOK_EVENTS`) |
| `session_id` | string | Session identifier (UUID) |
| `meeting_url` | string | The meeting that was joined |
| `reference` | string or null | The caller's reference from `/join`, `null` when none was given |
| `status` | string | The session status, see [API](api.md#session-status). For `finished`: `stopped`, `denied`, `not_admitted`, `error` or `interrupted` |
| `error_message` | string or null | Why it failed, when it did |
| `file_location` | string | Local path, blob path or object URL; `.wav` or `.flac` per `RECORDING_FORMAT`. Empty when there is no recording |
| `started_at`, `stopped_at` | ISO 8601 | When the session started and stopped |
| `sequence` | integer | Counts the webhooks of one session. Ignore one whose sequence is not higher than the last you applied |
| `occurred_at` | ISO 8601 | When this event happened, not when it was delivered |

## Status events

With `WEBHOOK_EVENTS=true` the session reports each step: `joining` (browser starting), `lobby` (asked to be let in), `recording` or `connected` (in the meeting), then the `finished` webhook. Without it only `finished` is sent, as before.

## Delivery

Every webhook is written to `RECORDINGS_DIR/.outbox` before it is sent, and only removed once the receiver answers 200, 201, 202 or 204. Until then it is retried, with pauses growing from 5 seconds to 10 minutes, across restarts of the recorder. The webhooks of one session are delivered in order: a later one waits until the earlier one is through.

With remote storage the upload belongs to the `finished` webhook: the file is uploaded right before it is sent, retried the same way, so `file_location` never points at a local file the receiver cannot reach.

After `WEBHOOK_RETRY_HOURS` (24) an item is given up on and moved to `RECORDINGS_DIR/.outbox/failed`, where it stays for a human. Because a webhook can arrive more than once (a retry after a lost answer), receivers should treat a repeated `session_id` and `sequence` as already handled.

Set `WEBHOOK_SECRET` to have it sent as the `X-Webhook-Secret` header.

## Interrupted sessions

A running session keeps a small journal in `RECORDINGS_DIR/.sessions`. If the recorder stops while sessions are running (a crash, a container restart, a redeploy), the next start finds them there: it removes their audio devices, repairs the recording made so far (its header was never finalised) and reports each one as `finished` with status `interrupted`, its `reference` and the repaired recording. Nothing that was recorded is lost, and no session is left without an answer.
