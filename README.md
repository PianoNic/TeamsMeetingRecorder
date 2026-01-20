# <p align="center">TeamsMeetingRecorder</p>
<p align="center">
  <strong>A headless bot that automatically joins Microsoft Teams meetings and records audio.</strong>
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
TeamsMeetingRecorder is a Docker-based bot that automates Teams meeting participation and audio recording. It uses browser automation to join meetings, processes audio through isolated PulseAudio sinks, and provides a REST API for controlling recording sessions.

## ✨ Features
- **REST API**: Control bot via HTTP endpoints (FastAPI)
- **Browser Automation**: Modern Playwright-based browser control
- **Multi-Session Support**: Record multiple meetings simultaneously with isolated audio
- **High-Quality Audio**: 48kHz stereo recording with session-specific PulseAudio sinks
- **Automatic Participant Detection**: Leaves meeting when alone
- **Flexible Storage**: Save recordings locally or to MinIO/S3-compatible storage
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
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**2. Start it:**
```bash
docker compose up -d
```

The API will be available at [http://localhost:8000](http://localhost:8000)  
Swagger docs at [http://localhost:8000/docs](http://localhost:8000/docs)

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

**1. Set environment variables:**
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
      - STORAGE_BACKEND=minio
      - MINIO_ENDPOINT=${MINIO_ENDPOINT}
      - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
      - MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
      - MINIO_BUCKET=${MINIO_BUCKET}
      - MINIO_SECURE=${MINIO_SECURE}
    # Remove the recordings volume mount if not needed
```

#### Option 2: Run MinIO Locally (Recommended for Testing)

Use the included `minio.compose.yml` to run MinIO alongside the recorder:

**1. Create `.env` file:**
```env
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=recordings
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