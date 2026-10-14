# Self-hosting

## Docker

```bash
docker run -d \
  -p 8000:8000 \
  -v ./recordings:/app/recordings \
  --shm-size=2gb \
  --init \
  --name teams-recorder \
  ghcr.io/pianonic/teamsmeetingrecorder:latest
```

Also on Docker Hub as `pianonic/teamsmeetingrecorder`. The API is then at <http://localhost:8000>, its docs at <http://localhost:8000/docs>.

`--shm-size=2gb` keeps Chromium from crashing on `/dev/shm`. `--init` reaps the browser's child processes.

## Docker Compose

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
      - RECORDING_FORMAT=${RECORDING_FORMAT:-wav}
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

All settings are listed in [Configuration](configuration.md).

## Storage

Recordings land in `/app/recordings` first. With a remote backend they are uploaded once the meeting ends and the local copy is removed; files are keyed by session id.

### Azure Blob or Azurite

```env
STORAGE_BACKEND=azure
AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true
AZURE_STORAGE_CONTAINER=meeting-recordings
```

To bring up [Azurite](https://github.com/Azure/Azurite) next to the recorder:

```bash
docker compose -f azurite.compose.yml up -d
```

The webhook's `file_location` is `meeting-recordings/{session}/{file}`, or a full HTTP URL when `AZURE_STORAGE_PUBLIC_ENDPOINT` is set. The container is created if it is missing.

**On Azure App Service** the app's managed identity can replace the connection string: set `AZURE_STORAGE_ACCOUNT_URL` instead, give the identity *Storage Blob Data Contributor* on the account, and create the container yourself (the bot does not create it in this mode). This composes with `${NAME}` references when the platform already exposes these values under its own names:

```env
STORAGE_BACKEND=azure
AZURE_STORAGE_ACCOUNT_URL=${Storage__BlobServiceUri}
AZURE_STORAGE_CONTAINER=${Storage__BlobContainerName}
```

### S3 (any provider)

One backend for every S3-compatible store. Leave `S3_ENDPOINT_URL` unset for AWS:

```env
STORAGE_BACKEND=s3
S3_BUCKET=recordings
S3_REGION=eu-central-1
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
```

Other providers only add their endpoint, and self-hosted servers usually want path-style addressing:

| Provider | `S3_ENDPOINT_URL` | `S3_REGION` | `S3_FORCE_PATH_STYLE` |
|---|---|---|---|
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` | `auto` | – |
| Hetzner Object Storage | `https://fsn1.your-objectstorage.com` | `fsn1` | – |
| Wasabi | `https://s3.eu-central-1.wasabisys.com` | `eu-central-1` | – |
| Backblaze B2 | `https://s3.eu-central-003.backblazeb2.com` | `eu-central-003` | – |
| Self-hosted (Ceph, Garage, SeaweedFS, ...) | `http://s3.internal:9000` | any | `true` |

Without `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` the default AWS credential chain is used, e.g. the instance role on EC2 or ECS. The bucket is created when it is missing and the keys may do so; keys scoped to one existing bucket are the normal case.

The webhook's `file_location` is `{bucket}/{session}/{file}`, or a full URL when `S3_PUBLIC_ENDPOINT` is set.

`STORAGE_BACKEND=minio` and the `MINIO_*` settings were replaced by this backend: a MinIO server works as a self-hosted S3 endpoint with `S3_FORCE_PATH_STYLE=true`.
