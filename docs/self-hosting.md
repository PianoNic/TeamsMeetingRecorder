# Self-hosting

TeamsRecorder ships as one container image, built for x86-64 and ARM64:

- GitHub: `ghcr.io/pianonic/teamsmeetingrecorder`
- Docker Hub: `pianonic/teamsmeetingrecorder`

Tags follow the releases: `latest`, `1`, `1.4` and `1.4.0`.

## Run it

::: code-group

```bash [docker run]
docker run -d \
  -p 8000:8000 \
  -v ./recordings:/app/recordings \
  --shm-size=2gb \
  --init \
  --restart unless-stopped \
  --name teams-recorder \
  ghcr.io/pianonic/teamsmeetingrecorder:latest
```

```yaml [compose.yml]
services:
  teams-recorder:
    image: ghcr.io/pianonic/teamsmeetingrecorder:latest
    container_name: teams-recorder
    ports:
      - "8000:8000"
    volumes:
      - ./recordings:/app/recordings
    shm_size: "2gb"
    init: true
    restart: unless-stopped
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

:::

The API is then at <http://localhost:8000>, with interactive docs at <http://localhost:8000/docs>.

| Flag | Why |
|---|---|
| `--shm-size=2gb` | Chromium keeps its shared memory in `/dev/shm`; Docker's default 64 MB makes it crash in longer meetings |
| `--init` | Reaps the browser's child processes, which would otherwise pile up as zombies |
| `-v ./recordings:/app/recordings` | Keeps recordings, the session journal and undelivered webhooks across container replacements, see [interrupted sessions](./how-it-works.md#when-the-recorder-stops-mid-session) |

All settings go into the environment or a `.env` file, see [Configuration](./configuration.md). A good starting point:

```dotenv
RECORDING_FORMAT=flac
BOT_ACCESS_TOKEN=a-long-random-value
WEBHOOK_URL=https://your-app.example.com/hooks/recorder
WEBHOOK_SECRET=another-long-random-value
```

::: warning Do not expose it without a token
Anyone who can reach the API can send the bot into meetings. Set `BOT_ACCESS_TOKEN`, or keep the port on a private network. See [Consent and privacy](./privacy.md#securing-the-api).
:::

## Storage

Recordings are always written to `/app/recordings` first. With a remote backend they are uploaded when the session ends, and the local copy is deleted once the upload succeeded. Files are grouped by session id.

::: code-group

```dotenv [Local]
STORAGE_BACKEND=local
# Files stay in RECORDINGS_DIR (/app/recordings), mount it as a volume.
```

```dotenv [Azure]
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...
AZURE_STORAGE_CONTAINER=meeting-recordings
```

```dotenv [Azure identity]
STORAGE_BACKEND=azure
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=meeting-recordings
```

```dotenv [AWS]
STORAGE_BACKEND=s3
S3_BUCKET=recordings
S3_REGION=eu-central-1
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
```

```dotenv [R2]
STORAGE_BACKEND=s3
S3_BUCKET=recordings
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
```

```dotenv [Own S3]
STORAGE_BACKEND=s3
S3_BUCKET=recordings
S3_ENDPOINT_URL=http://s3.internal:9000
S3_FORCE_PATH_STYLE=true
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
```

:::

### Azure Blob Storage

With a connection string the container is created if it is missing. The webhook's `file_location` is `<container>/<session>/<file>`, or a full URL when `AZURE_STORAGE_PUBLIC_ENDPOINT` is set.

**Managed identity** (for example on Azure App Service or Container Apps): set `AZURE_STORAGE_ACCOUNT_URL` instead of a connection string, give the identity the *Storage Blob Data Contributor* role on the account, and create the container yourself. In this mode the bot does not create it.

When your platform already exposes these values under its own names, reference them instead of copying them:

```dotenv
STORAGE_BACKEND=azure
AZURE_STORAGE_ACCOUNT_URL=${Storage__BlobServiceUri}
AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}
```

To try it locally against [Azurite](https://github.com/Azure/Azurite), the repository has a ready-made setup:

```bash
docker compose -f azurite.compose.yml up -d
```

### S3, any provider

One backend covers every S3-compatible store. Leave `S3_ENDPOINT_URL` unset for AWS; other providers only add their endpoint:

| Provider | `S3_ENDPOINT_URL` | `S3_REGION` | `S3_FORCE_PATH_STYLE` |
|---|---|---|---|
| AWS S3 | (unset) | e.g. `eu-central-1` | – |
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` | `auto` | – |
| Hetzner Object Storage | `https://fsn1.your-objectstorage.com` | `fsn1` | – |
| Wasabi | `https://s3.eu-central-1.wasabisys.com` | `eu-central-1` | – |
| Backblaze B2 | `https://s3.eu-central-003.backblazeb2.com` | `eu-central-003` | – |
| Self-hosted (MinIO, Ceph, Garage, SeaweedFS, ...) | `http://s3.internal:9000` | any | `true` |

Without `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`, the default AWS credential chain is used, such as the instance role on EC2 or ECS. The bucket is created when it is missing and the keys are allowed to; keys scoped to one existing bucket are the usual case.

The webhook's `file_location` is `<bucket>/<session>/<file>`, or a full URL when `S3_PUBLIC_ENDPOINT` is set.

::: info Coming from MinIO settings?
`STORAGE_BACKEND=minio` and the `MINIO_*` settings were replaced by this backend. With the old value the bot fails with an error naming the replacement as soon as it stores a recording, instead of silently keeping it inside the container. A MinIO server keeps working as a self-hosted endpoint with `S3_FORCE_PATH_STYLE=true`.
:::

## Updating

Pull the new image and recreate the container. Sessions that are running at that moment are reported as `interrupted` on the next start, with what they recorded, so schedule updates between meetings when you can.

```bash
docker compose pull && docker compose up -d
```
