# Configuration

Set these as environment variables or in a `.env` file. A value may reference another environment variable as `${NAME}`, e.g. `AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}`, to reuse a platform-managed value instead of copying it.

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
| `STORAGE_BACKEND` | `local` | `local`, `azure` or `minio` |
| `AZURE_STORAGE_CONNECTION_STRING` | – | Azure or Azurite connection string. Either this or `AZURE_STORAGE_ACCOUNT_URL` |
| `AZURE_STORAGE_ACCOUNT_URL` | – | Account URL authenticated with the managed identity instead of a key. The container must already exist |
| `AZURE_STORAGE_CONTAINER` | `meeting-recordings` | Blob container name |
| `AZURE_STORAGE_PUBLIC_ENDPOINT` | – | Public blob base URL used in the webhook `file_location` |
| `MINIO_ENDPOINT` | – | e.g. `minio.example.com:9000` |
| `MINIO_ACCESS_KEY` | – | MinIO access key |
| `MINIO_SECRET_KEY` | – | MinIO secret key |
| `MINIO_BUCKET` | `recordings` | Bucket name |
| `MINIO_SECURE` | `true` | Use HTTPS for MinIO |

## Webhooks and access

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_URL` | – | Called when a session ends. Unset disables webhooks |
| `WEBHOOK_EVENTS` | `false` | Also call it for every status change while a session runs (`joining`, `lobby`, `recording`, ...) |
| `WEBHOOK_RETRY_HOURS` | `24` | How long an undeliverable webhook is retried before it is set aside in `RECORDINGS_DIR/.outbox/failed` |
| `WEBHOOK_SECRET` | – | Sent as `X-Webhook-Secret` for the receiver to verify. Unset sends no signature |
| `BOT_ACCESS_TOKEN` | – | Protects every endpoint except `/` and `/audio/{id}/ingest/{token}`. Requires `Authorization: Bearer <token>` or `X-API-Key`. Unset leaves the API open |
| `ACCESS_LOG` | `true` | One log line per HTTP request. `false` keeps only the recorder's own lines, useful when something polls `/sessions` or probes `/` |

## Microphone

| Variable | Default | Description |
|---|---|---|
| `MIC_PLAYBACK_ENABLED` | `false` | Give the bot a microphone it can play audio through. See [Microphone](microphone.md) for why this is opt-in |
| `DISABLE_NOISE_SUPPRESSION` | `true` | Turn off Teams' noise suppression after joining, so music is not treated as noise. Only with `MIC_PLAYBACK_ENABLED` |
| `PLAYBACK_IN_RECORDING` | `true` | Include what the bot played in the saved recording, not just what it heard |
| `MEDIA_DIR` | `/app/media` | The only directory `/audio/{id}/play` reads from. Uploads land here too |
| `MAX_UPLOAD_MB` | `100` | Cap on a single upload to `/audio/{id}/play/upload` |
| `PUBLIC_BASE_URL` | – | Base URL used to build the ingest URL, for deployments behind a proxy. Unset uses the request's own host |
