---
# Room for the wide diagrams, see custom.css.
aside: false
---

# Microphone

The bot can also talk: play a file, an upload or a live stream (for example text to speech) into the meeting. Recording needs no configuration; the microphone is opt-in, because it changes how the browser is launched:

```bash
MIC_PLAYBACK_ENABLED=true
```

::: details Why it is opt-in
The recorder launches Chromium with `--use-fake-device-for-media-stream`, which supplies a fake camera *and* replaces every microphone with a generated beep. A bot using that fake microphone cannot be heard whatever it plays, so enabling playback drops the flag, and with it the fake camera. Teams then puts an "are you sure you don't want audio or video?" prompt over the prejoin screen, which the bot dismisses on this path only. With `MIC_PLAYBACK_ENABLED` off, the browser flags and the join path stay exactly as they were.
:::

## How the audio flows

Audio reaches the meeting through a second PulseAudio sink, kept apart from the recording sink on purpose: pointing the microphone at the sink the browser also plays into would feed the meeting straight back to itself.

The sink's monitor is not handed to the browser directly. Chromium does not list monitor sources at all, so `getUserMedia` would find no microphone; `module-remap-source` turns the monitor into a real source that Teams lists and selects by name.

![How the audio flows](./diagrams/microphone.svg#gh-light-mode-only)
![How the audio flows](./diagrams/microphone-dark.svg#gh-dark-mode-only)

Teams' noise suppression is turned off once the bot is in the call. It is built to strip everything that is not a voice, which is exactly what music looks like to it. Set `DISABLE_NOISE_SUPPRESSION=false` to leave it on.

## Play a file

Mount your audio at `MEDIA_DIR` (`/app/media`) and play it by name. Paths outside that directory are refused, so an open API cannot be talked into reading arbitrary container files out loud.

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

Both unmute the bot first by default; pass `"unmute": false` (or `-F unmute=false`) to stage audio without being heard yet. Stop with `POST /audio/{session_id}/stop?mute_after=true`.

## Stream live audio in

Ask for an ingest URL and hand it to whatever produces the audio: a TTS engine, a player, another service. It carries its own secret, so it can be passed on without also handing over `BOT_ACCESS_TOKEN`.

```bash
curl -X POST http://localhost:8000/audio/{session_id}/stream \
  -H "Content-Type: application/json" -d '{}'
# {"ingest_url": "http://localhost:8000/audio/<id>/ingest/<token>", "token": "...", ...}
```

Anything ffmpeg can decode works (mp3, ogg, wav, webm), and the format is sniffed from the bytes. Push it with a chunked PUT:

```bash
ffmpeg -re -i some-source -f mp3 - | curl -T - "$INGEST_URL"

# or from a TTS service
curl -s https://tts.example.com/say?text=hello | curl -T - "$INGEST_URL"
```

The bot plays it as it arrives. Pushing faster than realtime blocks on the write rather than buffering, so the meeting stays in sync with the source. For headerless PCM, say so when opening the stream: `{"format": "s16le"}`. Close it with `DELETE /audio/{session_id}/stream`, which also invalidates the URL.

## Join without recording

Sometimes the bot is only there to say something. `record: false` joins, wires up the microphone and captures nothing: no file, no upload, and `/status` reports `connected` rather than `recording`.

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
       "display_name": "Announcer", "record": false}'
```

`MAX_RECORDING_MINUTES` still applies, so a speak-only bot cannot sit in a meeting forever.
