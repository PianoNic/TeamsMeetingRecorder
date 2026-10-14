# Webhooks

Set `WEBHOOK_URL` and the bot POSTs JSON to it when a session ends, whatever the outcome. With `WEBHOOK_EVENTS=true` it also reports every status change while the session runs.

```dotenv
WEBHOOK_URL=https://your-app.example.com/hooks/recorder
WEBHOOK_SECRET=a-long-random-value
WEBHOOK_EVENTS=true
```

## The payload

```json
{
  "event": "finished",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "reference": "order-4711",
  "status": "stopped",
  "error_message": null,
  "file_location": "recordings/550e8400-.../550e8400-..._20260121_143022.flac",
  "started_at": "2026-01-21T14:30:22.123456",
  "stopped_at": "2026-01-21T15:35:45.654321",
  "sequence": 4,
  "occurred_at": "2026-01-21T15:35:46.001234"
}
```

| Field | Type | Description |
|---|---|---|
| `event` | string | `finished` when the session is over, `status` for a change while it runs |
| `session_id` | string | Session id (UUID) |
| `meeting_url` | string | The meeting that was joined |
| `reference` | string or null | Your `reference` from `/join`, `null` when none was given |
| `status` | string | The [session status](./how-it-works.md#statuses). For `finished`: `stopped`, `denied`, `not_admitted`, `error` or `interrupted` |
| `error_message` | string or null | Why it failed, when it did |
| `file_location` | string | Local path, blob path or object path (a full URL with a public endpoint configured). Empty when there is no recording |
| `started_at`, `stopped_at` | ISO 8601 | When the session started and stopped |
| `sequence` | integer | Counts the webhooks of one session, starting at 1 |
| `occurred_at` | ISO 8601 | When this happened, not when it was delivered |

## Status events

With `WEBHOOK_EVENTS=true` a session reports each step: `joining`, `lobby`, then `recording` (or `connected`), and finally the `finished` webhook. Useful to show live progress, such as "waiting in the lobby", in your own app. Without it only `finished` is sent.

## Delivery

Webhooks are built to arrive, even when your receiver or the recorder is down for a while.

- Every webhook is written to `RECORDINGS_DIR/.outbox` before it is sent, and removed only once your receiver answers `200`, `201`, `202` or `204`.
- Until then it is retried, with pauses growing from 5 seconds to 10 minutes, across restarts of the recorder.
- The webhooks of one session are delivered in order: a later one waits for the earlier one.
- With remote storage, the upload belongs to the `finished` webhook: the file is uploaded right before it is sent and retried the same way, so `file_location` never points at a file your receiver cannot reach.
- After `WEBHOOK_RETRY_HOURS` (24) a webhook is given up on and moved to `RECORDINGS_DIR/.outbox/failed`, where it stays for a human to look at.

::: warning A webhook can arrive twice
If the answer to a delivery is lost, the bot sends it again. Treat a `session_id` and `sequence` you have already handled as done, and ignore any webhook whose `sequence` is not higher than the last one you applied for that session.
:::

## Writing a receiver

Check the secret, ignore what you have already seen, answer quickly and do the real work afterwards:

::: code-group

```csharp [C# (ASP.NET Core)]
using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

var secret = Encoding.UTF8.GetBytes("a-long-random-value");
var lastSequence = new ConcurrentDictionary<string, int>(); // use your database in production

app.MapPost("/hooks/recorder", (HttpRequest request, RecorderEvent e) =>
{
    var given = Encoding.UTF8.GetBytes(request.Headers["X-Webhook-Secret"].ToString());
    if (!CryptographicOperations.FixedTimeEquals(given, secret))
        return Results.Unauthorized();

    if (e.Sequence <= lastSequence.GetValueOrDefault(e.SessionId))
        return Results.Ok(); // already handled
    lastSequence[e.SessionId] = e.Sequence;

    if (e.Event == "finished" && !string.IsNullOrEmpty(e.FileLocation))
    {
        // queue the recording for processing
    }
    return Results.Ok();
});

app.Run();

record RecorderEvent(
    [property: JsonPropertyName("event")] string Event,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("reference")] string? Reference,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("file_location")] string? FileLocation,
    [property: JsonPropertyName("sequence")] int Sequence);
```

```python [Python (FastAPI)]
import hmac
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()
SECRET = "a-long-random-value"
last_sequence: dict[str, int] = {}  # use your database in production

@app.post("/hooks/recorder")
async def recorder_webhook(
    request: Request,
    x_webhook_secret: str = Header(default=""),
):
    if not hmac.compare_digest(x_webhook_secret, SECRET):
        raise HTTPException(status_code=401)

    event = await request.json()
    session, sequence = event["session_id"], event["sequence"]
    if sequence <= last_sequence.get(session, 0):
        return {"ok": True}  # already handled
    last_sequence[session] = sequence

    if event["event"] == "finished" and event["file_location"]:
        ...  # queue the recording for processing

    return {"ok": True}
```

```js [Node.js (Express)]
import express from 'express'
import { timingSafeEqual } from 'node:crypto'

const app = express()
const SECRET = Buffer.from('a-long-random-value')
const lastSequence = new Map() // use your database in production

app.post('/hooks/recorder', express.json(), (req, res) => {
  const given = Buffer.from(req.get('X-Webhook-Secret') ?? '')
  if (given.length !== SECRET.length || !timingSafeEqual(given, SECRET)) {
    return res.sendStatus(401)
  }

  const { session_id, sequence, event, file_location } = req.body
  if (sequence <= (lastSequence.get(session_id) ?? 0)) return res.sendStatus(200) // already handled
  lastSequence.set(session_id, sequence)

  if (event === 'finished' && file_location) {
    // queue the recording for processing
  }
  res.sendStatus(200)
})

app.listen(5000)
```

:::

For a quick look at what the bot sends, the repository has `webhook_test_server.py`, which prints every webhook it receives.

## Interrupted sessions

A running session keeps a small journal in `RECORDINGS_DIR/.sessions`. If the recorder stops while sessions are running (a crash, a container restart, a redeploy), the next start finds them there. It removes their leftover audio devices, repairs the recording made so far (its header was never finalised), uploads it, and reports each session as `finished` with status `interrupted`, its `reference` and the repaired recording.

Nothing that was recorded is lost, and no session is left without an answer. See [How a session works](./how-it-works.md#when-the-recorder-stops-mid-session).
