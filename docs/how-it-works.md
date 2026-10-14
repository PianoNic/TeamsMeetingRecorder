---
# Room for the wide diagrams, see custom.css.
aside: false
---

# How a session works

Every `/join` starts a **session**: one bot, in one meeting, with its own browser and its own audio device. This page follows a session from the request to the finished file.

![How TeamsRecorder fits in](./diagrams/overview.svg#gh-light-mode-only)
![How TeamsRecorder fits in](./diagrams/overview-dark.svg#gh-dark-mode-only)

Your app sends the bot into a meeting, the bot joins Teams as a guest, records, stores the file, and tells your app where it is.

![Session lifecycle](./diagrams/lifecycle.svg#gh-light-mode-only)
![Session lifecycle](./diagrams/lifecycle-dark.svg#gh-dark-mode-only)

## Joining

The bot starts a headless Chromium on a virtual display and opens the meeting link. It joins the web client as a guest under the `display_name` you gave it, with camera and microphone switched off. Nothing is installed in your Teams tenant and no account is needed: to Teams, the bot is an anonymous guest like anyone who joins from a browser.

Each session gets its own PulseAudio sink. The browser plays the meeting into that sink, and only that session's recorder listens to it, so several meetings can be recorded at the same time without their audio mixing.

## The lobby

Most meetings hold guests in the lobby until someone admits them. The session status is `lobby` while it waits.

- Someone admits the bot: the session moves on to `recording`.
- Someone declines it: the session ends as `denied`. Trying again only helps if someone is ready to let it in.
- Nobody reacts within `TEAMS_WAIT_FOR_LOBBY` minutes (30 by default): the session ends as `not_admitted`. Worth trying again later.

## Recording

Once in the meeting, the bot records what the meeting sounds like to a participant: 48 kHz, 16-bit, stereo, written straight to disk as WAV or FLAC (`RECORDING_FORMAT`).

It checks every second whether it is still in the call and whether anyone else is. When it has been alone for five checks in a row, or Teams has removed it from the call, it leaves. A recording is also stopped after `MAX_RECORDING_MINUTES` (240 by default) and handled like any other.

You can end a session early with `POST /stop/{session_id}`.

::: tip Join without recording
`"record": false` in the `/join` body sends a bot that records nothing but can [speak](./microphone.md), for example to play an announcement. Its status is `connected` instead of `recording`.
:::

## Statuses

`GET /status/{session_id}` and every [webhook](./webhooks.md) report one of these. The failures are kept apart on purpose, so you can react to them without parsing `error_message`.

| Status | Meaning | What to do |
|---|---|---|
| `joining` | Starting the browser and opening the meeting | Wait |
| `lobby` | Asked to be let in, waiting for someone to admit it | Let it in |
| `recording` | In the meeting and recording | |
| `connected` | In the meeting without recording, joined with `"record": false` | |
| `stopped` | Finished normally. The recording is at `recording_file` or already uploaded | Fetch the file |
| `denied` | An organiser declined the bot in the lobby | Retry only if someone will let it in |
| `not_admitted` | Nobody reacted before `TEAMS_WAIT_FOR_LOBBY` ran out | Worth retrying later |
| `interrupted` | The recorder stopped while the session ran, see [below](#when-the-recorder-stops-mid-session) | Process the partial recording |
| `error` | A browser, audio or storage failure, see `error_message` | Check the logs |

## Storing the file

When the session ends, the recording is closed and, with a remote backend, uploaded:

| Backend | Where the file ends up |
|---|---|
| `local` | `RECORDINGS_DIR/<session_id>_<date>_<time>.<ext>` |
| `azure` | `<container>/<session_id>/<session_id>_<date>_<time>.<ext>` |
| `s3` | `<bucket>/<session_id>/<session_id>_<date>_<time>.<ext>` |

After a successful upload the local copy is deleted. See [Self-hosting](./self-hosting.md#storage) for setting up each backend.

## Telling you

With `WEBHOOK_URL` set, the bot POSTs a `finished` webhook with the outcome and the file location, and, with `WEBHOOK_EVENTS=true`, one for every status change on the way. Webhooks are written to disk before they are sent and retried until your endpoint accepts them, for up to 24 hours. See [Webhooks](./webhooks.md).

Without webhooks, poll `GET /status/{session_id}`. It keeps answering after the session is over.

## When the recorder stops mid-session

A crash, a container restart or a redeploy would normally lose every running session. TeamsRecorder keeps a small journal per session in `RECORDINGS_DIR/.sessions`, so on the next start it:

1. finds the sessions that were still running,
2. repairs their recordings (the file header was never finalised),
3. uploads them like any other,
4. reports each one as `finished` with status `interrupted`.

Nothing that was recorded is lost, and every session gets an answer. Keep `RECORDINGS_DIR` on a volume for this to survive a container being replaced.

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

While a session with that reference is active, another `/join` with the same reference returns that session instead of sending a second bot. So when a `/join` times out, just send it again. The reference (up to 200 characters) comes back on `/sessions`, `/status`, `/stop` and every [webhook](./webhooks.md), so each report can be matched to your own record. Without a reference every `/join` sends a new bot.

::: tip All endpoints
Every running instance documents its whole API, with request and response shapes, at `http://localhost:8000/docs`.
:::
