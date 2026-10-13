# API

Interactive docs are served at `/docs` (Swagger).

```bash
# join a meeting and start recording
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://teams.microsoft.com/l/meetup-join/...", "display_name": "Recording Bot"}'

# check a session
curl http://localhost:8000/status/{session_id}

# stop early (it stops on its own when the meeting empties)
curl -X POST http://localhost:8000/stop/{session_id}

# list running sessions
curl http://localhost:8000/sessions
```

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Health probe and version. Never requires auth |
| `/join` | POST | Join a meeting and start recording. Returns a session id |
| `/status/{id}` | GET | Session state, uptime and recording path. Answers after the session ended too |
| `/stop/{id}` | POST | Stop a running session |
| `/sessions` | GET | The sessions currently running, with meeting URL and reference |
| `/audio/{id}` | GET | Microphone and playback state for a session |
| `/audio/{id}/mute` · `/unmute` | POST | Mute or unmute the bot in the meeting |
| `/audio/{id}/play` | POST | Play a file from `MEDIA_DIR` through the microphone |
| `/audio/{id}/play/upload` | POST | Upload an audio file and play it straight away |
| `/audio/{id}/stream` | POST · DELETE | Open or close an ingest URL for live audio |
| `/audio/{id}/ingest/{token}` | PUT · POST | Push a live audio stream in. Carries its own secret |
| `/audio/{id}/stop` | POST | Stop whatever is playing. `?mute_after=true` mutes too |

The `/audio` endpoints are described in [Microphone](microphone.md).

## Retrying a join safely

Pass your own id for the meeting as `reference`:

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://teams.microsoft.com/l/meetup-join/...", "display_name": "Recording Bot", "reference": "order-4711"}'
```

While a session with that reference is still active, another `/join` with the same reference returns that session instead of sending a second bot. So when a `/join` times out you can send it again without ending up with two bots in the meeting. The reference (up to 200 characters) comes back on `/sessions`, `/status`, `/stop` and the [webhook](webhooks.md), next to `meeting_url`, so every report can be matched to your own record. Without a reference nothing changes: every `/join` sends a new bot.

## Session status

`/status/{id}` reports one of these. The failure cases are kept apart on purpose, so a caller can act on them without reading `error_message`.

| Status | Meaning |
|---|---|
| `joining` | Asked to join, waiting in the lobby |
| `recording` | In the meeting and recording |
| `connected` | In the meeting but not recording, joined with `record: false` |
| `denied` | An organiser declined the bot from the lobby. It will not get in; retrying needs someone to let it through |
| `not_admitted` | Nobody accepted or declined the bot before `TEAMS_WAIT_FOR_LOBBY` ran out. Worth retrying later |
| `error` | Something went wrong: a browser, audio or storage failure. See `error_message` |
| `stopped` | Finished normally. The recording is at `recording_file` or already uploaded |
