# API overview

TeamsRecorder is controlled over a small HTTP API on port 8000. Requests and responses are JSON. A running instance also serves interactive Swagger docs at `/docs`.

Every endpoint has its own page in the **API reference** in the sidebar, generated from the OpenAPI schema, with its parameters, response shapes and a playground that sends real requests.

::: tip Trying a request
The playground runs in your browser and talks to `http://localhost:8000` by default. Pick *Custom Server* to point it at your own instance. With `BOT_ACCESS_TOKEN` set, add the token as an `Authorization: Bearer <token>` header.
:::

## The basics

```bash
# join a meeting and start recording
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://teams.microsoft.com/l/meetup-join/...", "display_name": "Recording Bot"}'

# follow a session
curl http://localhost:8000/status/{session_id}

# stop early (it also stops on its own when the meeting empties)
curl -X POST http://localhost:8000/stop/{session_id}

# list running sessions
curl http://localhost:8000/sessions
```

## Endpoints

### Sessions

| Endpoint | What it does |
|---|---|
| [`POST /join`](/operations/join_meeting_join_post) | Join a meeting and start recording. Returns the new session |
| [`GET /status/{id}`](/operations/get_status_status__session_id__get) | Status, timing and recording path. Keeps answering after the session ended |
| [`POST /stop/{id}`](/operations/stop_recording_stop__session_id__post) | End a running session; the recording is stored as usual |
| [`GET /sessions`](/operations/list_sessions_sessions_get) | The sessions running right now, with meeting link and reference |

### Microphone

| Endpoint | What it does |
|---|---|
| [`GET /audio/{id}`](/operations/get_audio_state_audio__session_id__get) | Microphone and playback state of a session |
| [`POST /audio/{id}/unmute`](/operations/unmute_audio__session_id__unmute_post), [`/mute`](/operations/mute_audio__session_id__mute_post) | Unmute or mute the bot in the meeting |
| [`POST /audio/{id}/play`](/operations/play_file_audio__session_id__play_post) | Play a file from `MEDIA_DIR` |
| [`POST /audio/{id}/play/upload`](/operations/play_upload_audio__session_id__play_upload_post) | Upload a file and play it right away |
| [`POST /audio/{id}/stream`](/operations/open_stream_audio__session_id__stream_post), [`DELETE`](/operations/close_ingest_stream_audio__session_id__stream_delete) | Open or close an ingest URL for live audio |
| [`PUT /audio/{id}/ingest/{token}`](/operations/ingest_audio_put) | Push live audio in. Carries its own secret |
| [`POST /audio/{id}/stop`](/operations/stop_playback_audio__session_id__stop_post) | Stop whatever is playing |

How these fit together is explained in [Microphone](./microphone.md).

### Health

| Endpoint | What it does |
|---|---|
| [`GET /`](/operations/root__get) | Name, version and number of running sessions. Never requires a token, made for health checks |

## Authentication

Without `BOT_ACCESS_TOKEN` the API is open. With it, every endpoint except `GET /` and the ingest URLs requires one of:

```http
Authorization: Bearer <token>
X-API-Key: <token>
```

## Session status

`status` is one of these. The failures are kept apart on purpose, so you can react to them without parsing `error_message`.

| Status | Meaning | What to do |
|---|---|---|
| `joining` | Starting the browser and opening the meeting | Wait |
| `lobby` | Asked to be let in, waiting for someone to admit it | Let it in |
| `recording` | In the meeting and recording | |
| `connected` | In the meeting without recording, joined with `"record": false` | |
| `stopped` | Finished normally. The recording is at `recording_file` or already uploaded | Fetch the file |
| `denied` | An organiser declined the bot in the lobby | Retry only if someone will let it in |
| `not_admitted` | Nobody reacted before `TEAMS_WAIT_FOR_LOBBY` ran out | Worth retrying later |
| `interrupted` | The recorder stopped while the session ran (crash, restart). Reported on the next start with what was recorded until then | Process the partial recording |
| `error` | A browser, audio or storage failure, see `error_message` | Check the logs |

## Retrying a join safely

Give the meeting your own id as `reference`:

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Recording Bot",
    "reference": "order-4711"
  }'
```

While a session with that reference is active, another `/join` with the same reference returns that session instead of sending a second bot. So when a `/join` times out, just send it again. The reference (up to 200 characters) comes back on `/sessions`, `/status`, `/stop` and every [webhook](./webhooks.md), so each report can be matched to your own record.

Without a reference every `/join` sends a new bot.
