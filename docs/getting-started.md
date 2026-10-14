# Getting started

TeamsRecorder runs as a single container. You send it a Teams meeting link over HTTP, and it does the rest: join, wait in the lobby, record, leave, store the file and let you know.

::: warning Get consent first
Recording people is regulated almost everywhere. Tell everyone in the meeting that it is being recorded and get their consent. See [Consent and privacy](./privacy.md).
:::

## Requirements

- Docker on an x86-64 or ARM64 host (the image is published for both)
- Room for one browser per meeting you record at the same time
- A Teams meeting that lets guests join. Anonymous join is a setting of the organiser's tenant

## 1. Start the recorder

```bash
docker run -d \
  -p 8000:8000 \
  -v ./recordings:/app/recordings \
  --shm-size=2gb \
  --init \
  --name teams-recorder \
  ghcr.io/pianonic/teamsmeetingrecorder:latest
```

Check that it is up:

```bash
curl http://localhost:8000/
```

```json
{ "name": "TeamsRecorder API", "version": "1.4.0", "status": "running", "active_sessions": 0 }
```

::: tip Why the extra flags
`--shm-size=2gb` gives Chromium enough shared memory; without it the browser crashes in longer meetings. `--init` cleans up the browser's child processes after each session.
:::

## 2. Send it into a meeting

Take the meeting's join link, for example from the invitation, and post it:

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Recording Bot"
  }'
```

```json
{
  "success": true,
  "message": "Bot joining with session ID: 550e8400-e29b-41d4-a716-446655440000",
  "session": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "reference": null,
    "display_name": "Recording Bot",
    "status": "joining",
    "record": true
  }
}
```

Someone in the meeting now sees *Recording Bot* waiting in the lobby and lets it in. The bot waits up to 30 minutes for that (`TEAMS_WAIT_FOR_LOBBY`).

## 3. Follow it

```bash
curl http://localhost:8000/status/550e8400-e29b-41d4-a716-446655440000
```

The status moves from `joining` to `lobby` to `recording`. All statuses are listed in [How a session works](./how-it-works.md#statuses).

## 4. Get the recording

The bot leaves on its own once it is the last one in the meeting. You can also stop it early:

```bash
curl -X POST http://localhost:8000/stop/550e8400-e29b-41d4-a716-446655440000
```

The recording is now in `./recordings` as `<session_id>_<date>_<time>.wav`. Set `RECORDING_FORMAT=flac` to get lossless FLAC at about a third of the size.

## Next steps

- [How a session works](./how-it-works.md): what happens between `/join` and the file
- [Self-hosting](./self-hosting.md): Docker Compose, and storing recordings in Azure or S3
- [Webhooks](./webhooks.md): get told when a recording is ready instead of polling
- [Configuration](./configuration.md): every setting
- Interactive API docs: every running instance serves them at <http://localhost:8000/docs>
