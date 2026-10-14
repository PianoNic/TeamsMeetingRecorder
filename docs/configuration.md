# Configuration

Set these as environment variables or in a `.env` file next to the container. Unknown keys are ignored, so a setting left over from an older version never stops the bot from starting.

A value may reference another environment variable as `${NAME}`, for example `AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}`, to reuse a value your platform already provides instead of copying it.

## Recording

| Variable | Default | Description |
|---|---|---|
| `TEAMS_WAIT_FOR_LOBBY` | `30` | Minutes to wait in the lobby before giving up |
| `RECORDINGS_DIR` | `/app/recordings` | Where recordings are written before upload |
| `RECORDING_FORMAT` | `wav` | `wav` or `flac`. Both hold the same 16-bit, 48 kHz samples; FLAC is lossless and a fraction of the size |
| `MAX_RECORDING_MINUTES` | `240` | Hard cap on a single recording. Stops and uploads normally when hit. `0` disables the cap |

### Choosing a format

Both formats contain exactly the same audio, bit for bit. WAV stores it as it is, about 11.5 MB per minute. FLAC compresses it without loss; because a meeting has the same signal on both channels, it usually ends up at around a quarter to a third of the WAV size. Pick WAV only if whatever reads the files cannot open FLAC.

## Storage

| Variable | Default | Description |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local`, `azure` or `s3` |
| `AZURE_STORAGE_CONNECTION_STRING` | – | Azure or Azurite connection string. Either this or `AZURE_STORAGE_ACCOUNT_URL` |
| `AZURE_STORAGE_ACCOUNT_URL` | – | Account URL authenticated with the managed identity instead of a key. The container must already exist |
| `AZURE_STORAGE_CONTAINER` | `meeting-recordings` | Blob container name |
| `AZURE_STORAGE_PUBLIC_ENDPOINT` | – | Public blob base URL used in the webhook `file_location` |
| `S3_BUCKET` | `recordings` | Bucket name |
| `S3_ENDPOINT_URL` | – | S3 endpoint of the provider. Unset means AWS |
| `S3_REGION` | – | Region, e.g. `eu-central-1`, or `auto` for Cloudflare R2 |
| `S3_ACCESS_KEY_ID` | – | Access key. Unset uses the default AWS credential chain (instance role, `AWS_*` variables) |
| `S3_SECRET_ACCESS_KEY` | – | Secret key |
| `S3_FORCE_PATH_STYLE` | `false` | Put the bucket in the path instead of the host name; most self-hosted servers need `true` |
| `S3_PUBLIC_ENDPOINT` | – | Public base URL used in the webhook `file_location` |

## Webhooks and access

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_URL` | – | Called when a session ends. Unset disables webhooks |
| `WEBHOOK_EVENTS` | `false` | Also call it for every status change while a session runs (`joining`, `lobby`, `recording`, ...) |
| `WEBHOOK_RETRY_HOURS` | `24` | How long an undeliverable webhook is retried before it is set aside in `RECORDINGS_DIR/.outbox/failed` |
| `WEBHOOK_SECRET` | – | Sent as `X-Webhook-Secret` for the receiver to verify. Unset sends no signature |
| `BOT_ACCESS_TOKEN` | – | Protects every endpoint except `/` and `/audio/{id}/ingest/{token}`. Requires `Authorization: Bearer <token>` or `X-API-Key`. Unset leaves the API open |
| `ACCESS_LOG` | `true` | One log line per HTTP request. `false` keeps only the recorder's own lines, useful when something polls `/sessions` or probes `/` |
| `STARTUP_WAIT_SECONDS` | `60` | How long the container waits at startup for PulseAudio and the virtual display. Both log how long they took; the display not coming up stops the container with the reason |

## Microphone

| Variable | Default | Description |
|---|---|---|
| `MIC_PLAYBACK_ENABLED` | `false` | Give the bot a microphone it can play audio through. See [Microphone](./microphone.md) for why this is opt-in |
| `DISABLE_NOISE_SUPPRESSION` | `true` | Turn off Teams' noise suppression after joining, so music is not treated as noise. Only with `MIC_PLAYBACK_ENABLED` |
| `PLAYBACK_IN_RECORDING` | `true` | Include what the bot played in the saved recording, not just what it heard |
| `MEDIA_DIR` | `/app/media` | The only directory `/audio/{id}/play` reads from. Uploads land here too |
| `MAX_UPLOAD_MB` | `100` | Cap on a single upload to `/audio/{id}/play/upload` |
| `PUBLIC_BASE_URL` | – | Base URL used to build the ingest URL, for deployments behind a proxy. Unset uses the request's own host |
