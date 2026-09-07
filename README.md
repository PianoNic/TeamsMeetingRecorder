<p align="center">
  <img src="./assets/TeamsRecorderTransparent.png" width="140" alt="TeamsMeetingRecorder logo">
</p>

<h1 align="center">TeamsMeetingRecorder</h1>

<p align="center">
  <strong>A bot that joins Microsoft Teams meetings and records the audio.</strong>
</p>

<p align="center">
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder"><img src="https://badgetrack.pianonic.ch/badge?tag=teams-meeting-recorder&label=visits&color=0d1117&style=flat" alt="visits" /></a>
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder/releases"><img src="https://img.shields.io/github/v/release/PianoNic/TeamsMeetingRecorder?include_prereleases&color=0d1117&label=Latest" alt="Latest release" /></a>
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder/blob/main/LICENSE"><img src="https://img.shields.io/github/license/PianoNic/TeamsMeetingRecorder?color=0d1117" alt="License" /></a>
  <a href="#get-started"><img src="https://img.shields.io/badge/Self--Host-Instructions-0d1117.svg" alt="Self-hosting" /></a>
  <img src="https://img.shields.io/badge/Python-3.12-0d1117.svg" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/FastAPI-0d1117.svg" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Playwright-0d1117.svg" alt="Playwright" />
</p>

---

> **Heads up:** not affiliated with, endorsed by, or connected to Microsoft in any way. And record responsibly — get explicit consent from every participant and check your local privacy law before you point this at a real meeting. See [Legal & privacy](#legal--privacy).

## What is TeamsMeetingRecorder?

A containerised bot that joins a Teams meeting as a guest and records what it hears. You POST a meeting link to the API, the bot joins through a real browser, waits out the lobby, records until the meeting empties, then hands the file to local disk, Azure Blob, or S3 and calls your webhook.

Each session is fully isolated: its own browser and its own PulseAudio sink, so several meetings can be recorded at once without their audio mixing.

## Features

- **REST API** — start, stop, and inspect sessions over HTTP (FastAPI, with Swagger at `/docs`).
- **Multi-session** — concurrent meetings each get a dedicated browser and audio sink, verified isolated end to end.
- **Leaves on its own** — detects when the meeting has emptied and stops, uploads, and cleans up without being told.
- **Flexible storage** — local disk, Azure Blob (or Azurite), or MinIO / any S3-compatible bucket.
- **Webhooks** — POST on completion, optionally signed with a shared secret.
- **Optional auth** — a bearer token in front of every endpoint except the health probe.
- **Speaks, not just listens** — opt in with `MIC_PLAYBACK_ENABLED`, then play a file or push a live stream to an ingest URL and the meeting hears it through the bot's microphone.
- **Record, speak, or both** — `record: false` joins a meeting purely to play audio in, capturing nothing.
- **48 kHz stereo** — recorded straight off a per-session virtual sink with `parec`.

## Get started

### Run the image

```bash
docker run -d \
  -p 8000:8000 \
  -v ./recordings:/app/recordings \
  --shm-size=2gb \
  --init \
  --name teams-recorder \
  ghcr.io/pianonic/teamsmeetingrecorder:latest
```

Also on Docker Hub as `pianonic/teamsmeetingrecorder`. The API is then at [http://localhost:8000](http://localhost:8000), docs at [/docs](http://localhost:8000/docs).

### Docker Compose

```yaml
services:
  teams-recorder:
    image: ghcr.io/pianonic/teamsmeetingrecorder:latest
    container_name: teams-meeting-recorder
    ports:
      - "8000:8000"
    volumes:
      - ./recordings:/app/recordings
    shm_size: '2gb'
    init: true
    restart: unless-stopped
    environment:
      - TEAMS_WAIT_FOR_LOBBY=${TEAMS_WAIT_FOR_LOBBY:-30}
      - STORAGE_BACKEND=${STORAGE_BACKEND:-local}
      - WEBHOOK_URL=${WEBHOOK_URL:-}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

```bash
docker compose up -d
```

> `--shm-size=2gb` keeps Chromium from crashing on `/dev/shm`. `--init` reaps the browser's child processes.

## Usage

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

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Health probe and version. Never requires auth. |
| `/join` | POST | Join a meeting and start recording. Returns a session id. |
| `/status/{id}` | GET | Session state, uptime, and recording path. Answers after the session ends. |
| `/stop/{id}` | POST | Stop a running session. |
| `/sessions` | GET | List the sessions currently running. |
| `/audio/{id}` | GET | Microphone and playback state for a session. |
| `/audio/{id}/mute` · `/unmute` | POST | Mute or unmute the bot in the meeting. |
| `/audio/{id}/play` | POST | Play a file from `MEDIA_DIR` through the microphone. |
| `/audio/{id}/play/upload` | POST | Upload an audio file and play it straight away. |
| `/audio/{id}/stream` | POST · DELETE | Open or close an ingest URL for live audio. |
| `/audio/{id}/ingest/{token}` | PUT · POST | Push a live audio stream in. Carries its own secret. |
| `/audio/{id}/stop` | POST | Stop whatever is playing. `?mute_after=true` mutes too. |

### Session status

`/status/{id}` reports one of these. The failure cases are distinct on purpose, so a caller can act on them without matching on `error_message`.

| Status | Meaning |
|---|---|
| `joining` | Requested to join, waiting in the lobby |
| `recording` | In the meeting and recording |
| `connected` | In the meeting but not recording — joined with `record: false` |
| `denied` | An organiser declined the bot from the lobby. It will not get in; retrying needs someone to let it through |
| `not_admitted` | Nobody accepted or declined the bot before `TEAMS_WAIT_FOR_LOBBY` ran out. Worth retrying later |
| `error` | Something went wrong — a browser, audio or storage failure. See `error_message` |
| `stopped` | Finished normally. The recording is at `recording_file` or already uploaded |

## Speaking into a meeting

Recording is the default and needs no configuration. Giving the bot a microphone is
opt-in, because it changes how the browser is launched:

```bash
MIC_PLAYBACK_ENABLED=true
```

**Why it is opt-in.** The recorder has always launched chromium with
`--use-fake-device-for-media-stream`, which supplies a fake camera *and* replaces every
microphone with a generated beep. A bot using that fake microphone cannot be heard no
matter what it plays, so enabling playback drops the flag — and with it the fake camera.
Teams then puts an "are you sure you don't want audio or video?" interstitial over the
prejoin screen, which the bot dismisses on this path only. With `MIC_PLAYBACK_ENABLED`
off, the browser flags and the join path are exactly what they have always been.

Audio reaches the meeting through a second PulseAudio sink, kept separate from the
recording sink on purpose — pointing the microphone at the sink the browser also plays
into would feed the meeting straight back to itself.

The sink's monitor is not handed to the browser directly. **Chromium does not enumerate
monitor sources at all**, so `getUserMedia` would find no microphone whatsoever;
`module-remap-source` turns the monitor into a real source that Teams lists and selects
by name.

```
  what it hears
      chromium ──PULSE_SINK──▶ teams_sink_<id> ──▶ parec ──▶ .wav
                                      ▲
                                      │ module-loopback   (PLAYBACK_IN_RECORDING)
                                      │
  what it says                        │
      chromium ◀─PULSE_SOURCE── teams_mic_src_<id> ◀── teams_mic_<id> ◀── pacat ◀── ffmpeg
                                (module-remap-source)                                  ▲
                                                                          a file, or an ingest stream
```

Teams' noise suppression is turned off once the bot is in the call. It is built to strip
everything that is not a voice, which is exactly what music looks like to it — set
`DISABLE_NOISE_SUPPRESSION=false` to leave it alone.

### Play a file

Mount your audio at `MEDIA_DIR` (`/app/media`) and play it by name. Paths outside that
directory are refused, so an open API cannot be talked into reading arbitrary container files
out loud.

```bash
curl -X POST http://localhost:8000/audio/{session_id}/play \
  -H "Content-Type: application/json" \
  -d '{"path": "hold-music.mp3", "loop": true, "volume": 1.0}'
```

Or upload one in the same request. The upload is deleted as soon as it finishes playing:

```bash
curl -X POST http://localhost:8000/audio/{session_id}/play/upload \
  -F file=@greeting.mp3
```

Both unmute the bot first by default; pass `"unmute": false` (or `-F unmute=false`) to stage
audio without being heard yet. Stop with `POST /audio/{session_id}/stop?mute_after=true`.

### Stream live audio in

Ask for an ingest URL and hand it to whatever produces the audio — a TTS engine, a player,
another service. It carries its own secret, so it can be passed on without also handing over
`BOT_ACCESS_TOKEN`.

```bash
curl -X POST http://localhost:8000/audio/{session_id}/stream \
  -H "Content-Type: application/json" -d '{}'
# {"ingest_url": "http://localhost:8000/audio/<id>/ingest/<token>", "token": "...", ...}
```

Anything ffmpeg can decode works — mp3, ogg, wav, webm — and the format is sniffed from the
bytes. Push it with a chunked PUT:

```bash
ffmpeg -re -i some-source -f mp3 - | curl -T - "$INGEST_URL"

# or from a TTS service
curl -s https://tts.example.com/say?text=hello | curl -T - "$INGEST_URL"
```

The bot plays it as it arrives. Pushing faster than realtime blocks on the write rather than
buffering, so the meeting stays in sync with the source. For headerless PCM, say so when
opening the stream: `{"format": "s16le"}`. Close it with `DELETE /audio/{session_id}/stream`,
which also invalidates the URL.

### Join without recording

Sometimes the bot is only there to say something. `record: false` joins, wires up the
microphone, and captures nothing — no file, no upload, and `/status` reports `connected`
rather than `recording`.

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
       "display_name": "Announcer", "record": false}'
```

`MAX_RECORDING_MINUTES` still applies, so a speak-only bot cannot sit in a meeting forever.

## Configuration

Set these as environment variables or in a `.env` file. A value may reference another environment variable as `${NAME}`, e.g. `AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}` to reuse a platform-managed value instead of duplicating it.

| Variable | Default | Description |
|---|---|---|
| `TEAMS_WAIT_FOR_LOBBY` | `30` | Minutes to wait in the lobby before giving up |
| `RECORDINGS_DIR` | `/app/recordings` | Where recordings are written before upload |
| `MAX_RECORDING_MINUTES` | `240` | Hard cap on a single recording. Stops and uploads normally when hit. `0` disables the cap |
| `STORAGE_BACKEND` | `local` | `local`, `azure`, or `minio` |
| `WEBHOOK_URL` | – | Called when a recording finishes. Unset disables webhooks |
| `WEBHOOK_SECRET` | – | Sent as `X-Webhook-Secret` for the receiver to verify. Unset sends no signature |
| `BOT_ACCESS_TOKEN` | – | Protects every endpoint except `/` and `/audio/{id}/ingest/{token}`. Requires `Authorization: Bearer <token>` or `X-API-Key`. Unset leaves the API open |
| `MIC_PLAYBACK_ENABLED` | `false` | Give the bot a microphone it can play audio through. Enabling it drops chromium's fake capture device, so the bot has no camera on the prejoin screen (handled) but can finally be heard |
| `DISABLE_NOISE_SUPPRESSION` | `true` | Turn off Teams' noise suppression after joining, so music is not treated as noise. Only applies when `MIC_PLAYBACK_ENABLED` is on |
| `PLAYBACK_IN_RECORDING` | `true` | Include what the bot played in the saved recording, not just what it heard |
| `MEDIA_DIR` | `/app/media` | The only directory `/audio/{id}/play` will read from. Uploads land here too |
| `MAX_UPLOAD_MB` | `100` | Cap on a single upload to `/audio/{id}/play/upload` |
| `PUBLIC_BASE_URL` | – | Base URL used to build the ingest URL, for deployments behind a proxy. Unset uses the request's own host |
| `AZURE_STORAGE_CONNECTION_STRING` | – | Azure / Azurite connection string (`STORAGE_BACKEND=azure`). Either this or `AZURE_STORAGE_ACCOUNT_URL` |
| `AZURE_STORAGE_ACCOUNT_URL` | – | Account URL authenticated with the managed identity instead of a key. Container must already exist |
| `AZURE_STORAGE_CONTAINER` | `meeting-recordings` | Blob container name |
| `AZURE_STORAGE_PUBLIC_ENDPOINT` | – | Public blob base URL used in the webhook `file_location` |
| `MINIO_ENDPOINT` | – | e.g. `minio.example.com:9000` (`STORAGE_BACKEND=minio`) |
| `MINIO_ACCESS_KEY` | – | MinIO access key |
| `MINIO_SECRET_KEY` | – | MinIO secret key |
| `MINIO_BUCKET` | `recordings` | Bucket name |
| `MINIO_SECURE` | `true` | Use HTTPS for MinIO |

## Storage

Recordings land in `/app/recordings` first. With a remote backend they are uploaded once the meeting ends and the local copy is removed; the bucket is created if missing and files are keyed by session id.

<details>
<summary><strong>Azure Blob / Azurite</strong></summary>

```env
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true
AZURE_STORAGE_CONTAINER=meeting-recordings
```

To bring up [Azurite](https://github.com/Azure/Azurite) alongside the recorder:

```bash
docker compose -f azurite.compose.yml up -d
```

`file_location` is sent as `meeting-recordings/{session}/{file}.wav`, or a full HTTP URL when `AZURE_STORAGE_PUBLIC_ENDPOINT` is set.

**On Azure App Service** you can skip the connection string and use the app's managed identity: set `AZURE_STORAGE_ACCOUNT_URL` instead, give the identity *Storage Blob Data Contributor* on the account, and make sure the container exists (the bot will not create it in this mode). No secret needed. This composes with `${NAME}` references when the platform already exposes these values under its own names:

```env
STORAGE_BACKEND=azure
AZURE_STORAGE_ACCOUNT_URL=${Storage__BlobServiceUri}
AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}
```

</details>

<details>
<summary><strong>MinIO / S3</strong></summary>

```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_BUCKET=recordings
MINIO_SECURE=true
```

To run MinIO locally alongside the recorder:

```bash
docker compose -f minio.compose.yml up -d
```

Console on [:9001](http://localhost:9001), API on [:9000](http://localhost:9000), recorder on [:8000](http://localhost:8000).

</details>

## Webhooks

Set `WEBHOOK_URL` and the bot POSTs JSON when a session ends — on success, and on failure with an empty `file_location`.

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "file_location": "meeting-recordings/550e8400-.../550e8400-..._20250121_143022.wav",
  "started_at": "2025-01-21T14:30:22.123456",
  "stopped_at": "2025-01-21T14:35:45.654321"
}
```

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Session identifier (UUID) |
| `meeting_url` | string | The meeting that was joined |
| `file_location` | string | Local path, blob path, or object URL. Empty when the recording failed |
| `started_at` | ISO 8601 | When the session started |
| `stopped_at` | ISO 8601 | When the session stopped |

POST with a 30 second timeout; 200, 201, 202, and 204 count as delivered. A failed webhook is logged and does not fail the recording. Set `WEBHOOK_SECRET` to have it sent as the `X-Webhook-Secret` header.

## Legal & privacy

Recording people has rules. Before you use this:

- Get **explicit consent** from every participant.
- Comply with local **privacy law** — GDPR, CCPA, and friends.
- Tell participants the meeting is being recorded.
- Do **not** expose this API publicly without `BOT_ACCESS_TOKEN` set.
- Use it for legitimate purposes only.

## License

See [LICENSE](LICENSE).

---

<p align="center">Made with care by <a href="https://github.com/PianoNic">PianoNic</a></p>
