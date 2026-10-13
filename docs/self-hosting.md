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

### MinIO or S3

```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_BUCKET=recordings
MINIO_SECURE=true
```

To run MinIO locally next to the recorder:

```bash
docker compose -f minio.compose.yml up -d
```

Console on <http://localhost:9001>, API on <http://localhost:9000>, recorder on <http://localhost:8000>. The bucket is created if it is missing.
