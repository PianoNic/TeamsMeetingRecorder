# <p align="center">TeamsMeetingRecorder</p>
<p align="center">
  <img src="./assets/TeamsRecorderTransparent.png" width="200" alt="TeamsMeetingRecorder Logo">
</p>

<p align="center">
  <strong>A simple bot that automatically joins Microsoft Teams meetings and records audio.</strong>
</p> 

<p align="center">
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder"><img src="https://badgetrack.pianonic.ch/badge?tag=teams-meeting-recorder&label=visits&color=5558d9&style=flat" alt="visits"/></a>
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder/blob/main/LICENSE"><img src="https://img.shields.io/github/license/PianoNic/TeamsMeetingRecorder?color=5558d9"/></a>
  <a href="https://github.com/PianoNic/TeamsMeetingRecorder/releases"><img src="https://img.shields.io/github/v/release/PianoNic/TeamsMeetingRecorder?include_prereleases&color=5558d9&label=Latest%20Release"/></a>
  <a href="#-docker--container-registry-usage"><img src="https://img.shields.io/badge/Selfhost-Instructions-5558d9.svg"/></a>
</p>

> [!IMPORTANT]
> This project is **NOT** affiliated with, endorsed by, or connected to Microsoft Teams or Microsoft Corporation in any way. This is an independent tool for automated meeting recording.

## ⚙️ About The Project
TeamsMeetingRecorder is a Docker-based bot that automates Teams meeting participation and audio recording. It uses browser automation to join meetings, processes audio through isolated [PulseAudio](https://de.wikipedia.org/wiki/PulseAudio) sinks, and provides a REST API for controlling recording sessions.

## ✨ Features
- **REST API**: Control bot via HTTP endpoints (FastAPI)
- **Browser Automation**: Modern Playwright-based browser control
- **Multi-Session Support**: Record multiple meetings simultaneously
- **High-Quality Audio**: 48kHz stereo recording
- **Automatic Participant Detection**: Leaves meeting when alone
- **Flexible Storage**: Save recordings locally or to MinIO/S3-compatible storage
- **Webhook Notifications**: Get notified when recordings complete (local or S3 upload)
- **Docker Ready**: Fully containerized with Docker Compose

## 🐳 Docker & Container Registry Usage

### Option 1: Pull and Run a Pre-built Image

**Docker Hub:**
```bash
docker pull pianonic/teamsmeetingrecorder:latest
```

**GitHub Container Registry:**
```bash
docker pull ghcr.io/pianonic/teamsmeetingrecorder:latest
```

Then run:
```bash
docker run -d \
  -p 8000:8000 \
  -v ./recordings:/app/recordings \
  --shm-size=2gb \
  --name teams-recorder \
  pianonic/teamsmeetingrecorder:latest
```

The API will be available at [http://localhost:8000](http://localhost:8000)

### Option 2: Run with Docker Compose (Recommended)

**1. Create a `compose.yaml` file:**
```yaml
services:
  teams-recorder:
    image: pianonic/teamsmeetingrecorder:latest
    # image: ghcr.io/pianonic/teamsmeetingrecorder:latest
    container_name: teams-meeting-recorder
    ports:
      - "8000:8000"
    volumes:
      - ./recordings:/app/recordings
    shm_size: '2gb'
    restart: unless-stopped
    environment:
      - TEAMS_WAIT_FOR_LOBBY=${TEAMS_WAIT_FOR_LOBBY:-30}
      - DEBUG_SCREENSHOTS=${DEBUG_SCREENSHOTS:-false}
      - STORAGE_BACKEND=${STORAGE_BACKEND:-local}
      - WEBHOOK_URL=${WEBHOOK_URL:-}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**2. (Optional) Create a `.env` file for configuration:**
```env
TEAMS_WAIT_FOR_LOBBY=10
DEBUG_SCREENSHOTS=false
STORAGE_BACKEND=local
```

**3. Start it:**
```bash
docker compose up -d
```

The API will be available at [http://localhost:8000](http://localhost:8000)
Swagger docs at [http://localhost:8000/docs](http://localhost:8000/docs)

## ⚙️ Configuration

TeamsMeetingRecorder can be configured using environment variables. Create a `.env` file in your project directory or set them in your `compose.yaml`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEAMS_WAIT_FOR_LOBBY` | `30` | Waiting room timeout in minutes before bot stops |
| `DEBUG_SCREENSHOTS` | `false` | Save screenshots during bot operation (set to `true` to enable) |
| `STORAGE_BACKEND` | `local` | Storage backend: `local` or `minio` |
| `MINIO_ENDPOINT` | - | MinIO server endpoint (e.g., `minio.example.com:9000`) |
| `MINIO_ACCESS_KEY` | - | MinIO access key |
| `MINIO_SECRET_KEY` | - | MinIO secret key |
| `MINIO_BUCKET` | `recordings` | MinIO bucket name |
| `MINIO_SECURE` | `true` | Use HTTPS for MinIO connection |
| `WEBHOOK_URL` | - | Webhook URL to notify when recording completes (optional) |

**Example `.env` file:**
```env
TEAMS_WAIT_FOR_LOBBY=10
DEBUG_SCREENSHOTS=false
STORAGE_BACKEND=local
WEBHOOK_URL=https://your-api.example.com/webhook
```

## 🚀 Usage

### Join a Meeting
```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Recording Bot"
  }'
```

### Check Status
```bash
curl http://localhost:8000/status/{session_id}
```

### Stop Recording
```bash
curl -X POST http://localhost:8000/stop/{session_id}
```

### List Active Sessions
```bash
curl http://localhost:8000/sessions
```

## 🗄️ Storage Configuration

TeamsMeetingRecorder supports two storage backends:

### Local Storage (Default)
Recordings are saved to the local filesystem (`/app/recordings` in container, mounted as `./recordings` on host).

No additional configuration needed.

### MinIO/S3 Storage
Store recordings in MinIO or any S3-compatible object storage.

#### Option 1: Use External MinIO/S3 Service

**1. Create/Update `.env` file:**
```env
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio.example.com:9000
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key
MINIO_BUCKET=recordings
MINIO_SECURE=true
```

**2. Update `compose.yaml`:**
```yaml
services:
  teams-recorder:
    environment:
      - TEAMS_WAIT_FOR_LOBBY=${TEAMS_WAIT_FOR_LOBBY:-30}
      - DEBUG_SCREENSHOTS=${DEBUG_SCREENSHOTS:-false}
      - STORAGE_BACKEND=${STORAGE_BACKEND:-local}
      - WEBHOOK_URL=${WEBHOOK_URL:-}
      - MINIO_ENDPOINT=${MINIO_ENDPOINT}
      - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
      - MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
      - MINIO_BUCKET=${MINIO_BUCKET:-recordings}
      - MINIO_SECURE=${MINIO_SECURE:-true}
    # Remove the recordings volume mount if not needed
```

#### Option 2: Run MinIO Locally (Recommended for Testing)

Use the included `minio.compose.yml` to run MinIO alongside the recorder:

**1. Create `.env` file:**
```env
TEAMS_WAIT_FOR_LOBBY=10
DEBUG_SCREENSHOTS=false
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=recordings
MINIO_SECURE=false
```

**2. Start both services:**
```bash
docker compose -f minio.compose.yml up -d
```

**Access:**
- **MinIO Console**: [http://localhost:9001](http://localhost:9001)
- **MinIO API**: [http://localhost:9000](http://localhost:9000)
- **API**: [http://localhost:8000](http://localhost:8000)

Login to MinIO Console with the credentials from your `.env` file (default: `minioadmin` / `minioadmin`).

**Features:**
- Automatic bucket creation if it doesn't exist
- Recordings uploaded after meeting ends
- Local temporary files cleaned up after successful upload
- Files organized by session ID in MinIO

## 🔔 Webhook Configuration

TeamsMeetingRecorder can notify your application when a recording finishes (both for local and MinIO storage) by sending an HTTP POST request to a configured webhook URL.

### Setup

**1. Add webhook URL to `.env` file:**
```env
WEBHOOK_URL=https://your-api.example.com/webhook
```

**2. The webhook URL is automatically picked up from environment variables in `compose.yaml`**

The webhook environment variable is already included in the Docker Compose examples above. Leave `WEBHOOK_URL` empty or unset to disable webhooks.

### Webhook Payload

When a recording completes or fails, the following JSON payload is sent to your webhook URL:

**Example with MinIO storage:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "file_location": "https://minio.example.com:9000/recordings/550e8400-e29b-41d4-a716-446655440000/550e8400-e29b-41d4-a716-446655440000_20250121_143022.wav",
  "started_at": "2025-01-21T14:30:22.123456",
  "stopped_at": "2025-01-21T14:35:45.654321"
}
```

**Example with local storage:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
  "file_location": "/app/recordings/550e8400-e29b-41d4-a716-446655440000_20250121_143022.wav",
  "started_at": "2025-01-21T14:30:22.123456",
  "stopped_at": "2025-01-21T14:35:45.654321"
}
```

### Webhook Details

- **Timeout**: 30 seconds
- **Method**: HTTP POST
- **Content-Type**: `application/json`
- **Success Status Codes**: 200, 201, 202, 204
- **Fire-and-Forget**: Webhook sends in background without blocking recording completion
- **Triggered On**:
  - ✅ Recording completes successfully (local storage)
  - ✅ Recording uploaded to MinIO/S3
  - ✅ Recording fails (sent with empty `file_location`)

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique identifier for the recording session (UUID) |
| `meeting_url` | string | The Teams meeting URL that was joined |
| `file_location` | string | Local file path (for local storage) or MinIO URL (for MinIO/S3 storage). Empty string if recording failed. |
| `started_at` | ISO 8601 | When the bot started the session |
| `stopped_at` | ISO 8601 | When the bot stopped the session |

## ⚠️ Legal & Privacy

**IMPORTANT:** Always obtain consent before recording!

- Get **explicit permission** from all meeting participants
- Comply with local **privacy laws** (GDPR, CCPA, etc.)
- Inform participants that recording is in progress
- Do **not** expose this API publicly without authentication
- Use only for **legitimate purposes** (documentation, compliance, etc.)

## 📜 License
This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---
<p align="center">Made with ❤️ by <a href="https://github.com/PianoNic">PianoNic</a></p>
<p align="center">
  <a href="https://buymeacoffee.com/pianonic"><img src="https://img.shields.io/badge/-buy_me_a%C2%A0coffee-gray?logo=buy-me-a-coffee" alt="Buy Me A Coffee"/></a>
</p>