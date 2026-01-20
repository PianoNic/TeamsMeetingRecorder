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

## Architektur

```
┌─────────────────┐
│   FastAPI       │ ← REST API Endpoints
│   (Port 8000)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Teams Bot      │ ← Playwright API
│  Controller     │   + Chromium Browser
└────────┬────────┘
         │
         ├─────────────────────┐
         │                     │
         ▼                     ▼
┌─────────────────┐   ┌─────────────────┐
│  Audio Recorder │   │  VNC Server     │
│  (PulseAudio)   │   │  (Port 5900)    │
└─────────────────┘   └─────────────────┘
```

## Voraussetzungen

- Docker (≥ 20.10)
- Docker Compose (≥ 2.0)
- 2GB freier RAM (für Browser und Audio-Processing)
- Internetzugang

## Installation

### 1. Repository klonen

```bash
git clone <repository-url>
cd TeamsMeetingRecorder
```

### 2. Environment-Datei erstellen (optional)

```bash
cp .env.example .env
# Bearbeite .env nach Bedarf
```

### 3. Mit Docker Compose starten

```bash
# Services bauen und starten (Docker Compose v2/v5 - 2026 Standard)
docker compose build
docker compose up -d
```

**Hinweis**: Wir verwenden `docker compose` (mit Leerzeichen) statt dem veralteten `docker-compose` (mit Bindestrich), entsprechend den 2026 Best Practices.

Die folgenden Services werden gestartet:
- **FastAPI**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **VNC**: localhost:5900 (Passwort: `teams123`)
- **noVNC Web**: http://localhost:8080

## Verwendung

### API-Endpoints

#### 1. Bot starten und Meeting beitreten

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Recording Bot",
    "record_audio": true,
    "max_duration_minutes": 60
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Bot is joining the meeting with session ID: abc-123-def",
  "session": {
    "session_id": "abc-123-def",
    "meeting_url": "https://teams.microsoft.com/...",
    "display_name": "Recording Bot",
    "status": "joining",
    "started_at": "2026-01-19T10:30:00Z"
  }
}
```

#### 2. Session-Status abfragen

```bash
curl http://localhost:8000/status/{session_id}
```

**Response:**
```json
{
  "session_id": "abc-123-def",
  "status": "recording",
  "uptime_seconds": 125.5,
  "recording_duration_seconds": 120.0,
  "recording_file": "/app/recordings/abc-123-def_20260119_103000.wav"
}
```

#### 3. Recording stoppen

```bash
curl -X POST http://localhost:8000/stop/{session_id}
```

#### 4. Alle aktiven Sessions anzeigen

```bash
curl http://localhost:8000/sessions
```

#### 5. Aufnahme herunterladen

```bash
curl -O http://localhost:8000/download/{session_id}
```

### Python-Client Beispiel

```python
import requests
import time

API_BASE = "http://localhost:8000"

# Meeting beitreten
response = requests.post(f"{API_BASE}/join", json={
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Bot Recorder",
    "record_audio": True,
    "max_duration_minutes": 30
})

session = response.json()["session"]
session_id = session["session_id"]
print(f"Session gestartet: {session_id}")

# Status überprüfen
time.sleep(10)
status = requests.get(f"{API_BASE}/status/{session_id}").json()
print(f"Status: {status['status']}")

# Nach Meeting stoppen
# requests.post(f"{API_BASE}/stop/{session_id}")
```

### VNC-Zugriff

#### Option 1: noVNC (Web-Browser)

Öffne http://localhost:8080 in deinem Browser. Kein zusätzlicher Client erforderlich!

#### Option 2: VNC-Client

```bash
# Mit VNC-Client verbinden
vncviewer localhost:5900
# Passwort: teams123
```

Empfohlene VNC-Clients:
- **macOS**: Screen Sharing (vnc://localhost:5900)
- **Windows**: TightVNC, RealVNC
- **Linux**: Remmina, Vinagre

## Konfiguration

### Umgebungsvariablen

Siehe `.env.example` für alle verfügbaren Optionen:

| Variable | Beschreibung | Standard |
|----------|--------------|----------|
| `API_PORT` | FastAPI Port | `8000` |
| `VNC_PORT` | VNC Server Port | `5900` |
| `DISPLAY_WIDTH` | Browser-Breite | `1920` |
| `DISPLAY_HEIGHT` | Browser-Höhe | `1080` |
| `DEFAULT_SAMPLE_RATE` | Audio Sample Rate | `48000` |
| `DEFAULT_CHANNELS` | Audio-Kanäle | `2` |
| `RECORDINGS_DIR` | Aufnahme-Verzeichnis | `/app/recordings` |
| `LOGS_DIR` | Log-Verzeichnis | `/app/logs` |

### Docker Compose Anpassungen

Bearbeite `compose.yaml` (nicht mehr `docker-compose.yml` - deprecated seit 2023):

```yaml
# Mehr RAM für Browser
shm_size: '4gb'

# Zusätzliche Ports
ports:
  - "8000:8000"
  - "5900:5900"
  - "8080:8080"  # noVNC

# Volume für persistente Daten
volumes:
  - ./recordings:/app/recordings
  - ./logs:/app/logs
```

**2026 Update**: Die `version:` Angabe wird nicht mehr benötigt und ist deprecated.

## Entwicklung

### Lokale Entwicklung (ohne Docker)

```bash
# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Dependencies installieren
pip install -r requirements.txt

# API starten
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Hinweis**: Für lokale Entwicklung werden trotzdem Xvfb, Chrome, und PulseAudio benötigt.

### Docker Compose Befehle

```bash
docker compose build              # Docker Image bauen
docker compose up -d              # Services starten
docker compose down               # Services stoppen
docker compose logs -f            # Logs anzeigen
docker compose exec teams-recorder bash  # Shell im Container öffnen
docker compose down -v            # Alles aufräumen
```

## Troubleshooting

### Bot kann Meeting nicht beitreten

1. Überprüfe, ob die Teams-URL korrekt ist
2. Schaue über VNC/noVNC zu, was der Bot sieht
3. Prüfe die Logs: `docker compose logs -f teams-recorder`

### Keine Audio-Aufnahme

1. Überprüfe Audio-Geräte:
   ```bash
   docker compose exec teams-recorder pactl list sinks short
   ```

2. Teste Audio-Setup:
   ```bash
   make test-devices
   ```

3. Erhöhe Shared Memory:
   ```yaml
   shm_size: '4gb'  # in compose.yaml
   ```

### Browser stürzt ab

- Erhöhe `shm_size` in compose.yaml auf mindestens `2gb`
- Reduziere `DISPLAY_WIDTH` und `DISPLAY_HEIGHT`

### VNC verbindet nicht

```bash
# Überprüfe, ob VNC-Server läuft
docker compose exec teams-recorder ps aux | grep x11vnc

# Starte VNC manuell
docker compose exec teams-recorder x11vnc -display :99 -forever -shared
```

## Best Practices (2026)

Dieses Projekt folgt den neuesten Best Practices:

- **Playwright statt Selenium**: 30-50% bessere Performance und geringere Infrastruktur-Kosten
- **Auto-Waiting**: Playwright's eingebautes Auto-Waiting reduziert flaky Tests
- **Browser Context Model**: Effiziente Resource-Nutzung in Docker/Kubernetes
- **Docker Compose v2/v5**: Verwendet `docker compose` statt deprecated `docker-compose`
- **compose.yaml**: Moderne Compose-Datei ohne deprecated `version:` Feld
- **Multi-Stage Docker Builds**: Kleinere Images, bessere Security
- **Non-root User**: Container läuft als `botuser` (UID 1000)
- **Health Checks**: Automatische Gesundheitsüberwachung
- **Minimal Base Images**: Python 3.13 Slim Bookworm
- **Layer Caching**: Optimierte Dockerfile-Struktur
- **Shared Memory**: `--shm-size=2gb` für Browser-Stabilität
- **Logging**: Strukturiertes Logging mit Rotation
- **sounddevice**: Moderne Audio-Bibliothek statt PyAudio

## Technologie-Stack

- **Python 3.13**: Moderne Python-Version
- **FastAPI**: Hochperformantes Web-Framework
- **Playwright**: Moderne Browser-Automatisierung (2026 Standard, 30-50% effizienter als Selenium)
- **sounddevice**: Audio-Recording mit NumPy
- **PulseAudio**: Virtual Audio Sink
- **Xvfb**: Virtual Display Server
- **x11vnc**: VNC Server
- **Docker Compose v2**: Containerisierung

## Sicherheitshinweise

⚠️ **WICHTIG**: Dieser Bot ist für interne/private Nutzung gedacht!

- Immer die **Einwilligung aller Teilnehmer** einholen
- Beachte lokale **Datenschutzgesetze** (DSGVO, etc.)
- Nutze **sichere Passwörter** für VNC
- Exponiere die API **nicht** ungeschützt ins Internet
- Implementiere **Authentifizierung** für Produktionsumgebungen

## Quellen und Best Practices

Dieses Projekt basiert auf aktuellen (2026) Best Practices:

### Browser-Automatisierung
- [Playwright Python Best Practices](https://www.browserstack.com/guide/playwright-best-practices)
- [Playwright vs Selenium 2026](https://www.browserstack.com/guide/playwright-vs-selenium)
- [Playwright Docker Optimization](https://dev.to/deepak_mishra_35863517037/playwright-vs-selenium-a-2026-architecture-review-347d)
- [CueMeet Teams Bot](https://github.com/CueMeet/cuemeet-teams-bot)
- [MS Teams Auto Call Recorder](https://github.com/BartlomiejRasztabiga/ms-teams-auto-call-recorder)
- [Recall.ai: How to Build a Teams Bot](https://www.recall.ai/blog/how-to-build-a-microsoft-teams-bot)

### Docker Best Practices
- [Docker Compose v2 Migration](https://www.docker.com/blog/new-docker-compose-v2-and-v1-deprecation/)
- [compose.yaml vs docker-compose.yml](https://docs.docker.com/compose/intro/compose-application-model/)
- [Docker Multi-Stage Builds Guide](https://docs.docker.com/build/building/multi-stage/)
- [FastAPI Docker Best Practices](https://betterstack.com/community/guides/scaling-python/fastapi-docker-best-practices/)
- [Docker Compose Health Checks](https://last9.io/blog/docker-compose-health-checks/)

### Audio-Recording
- [SoundCard Python Library](https://github.com/bastibe/SoundCard)
- [PulseAudio Loopback Tool](https://github.com/alentoghostflame/Python-Pulseaudio-Loopback-Tool)

## Lizenz

MIT License - Siehe [LICENSE](LICENSE) Datei

## Autor

Erstellt mit Claude Code unter Verwendung der neuesten 2026 Best Practices für Docker, FastAPI, und Browser-Automatisierung.

## Support

Bei Fragen oder Problemen:
1. Überprüfe die Logs: `make logs`
2. Schaue via VNC zu: http://localhost:8080
3. Prüfe die API-Docs: http://localhost:8000/docs
4. Erstelle ein GitHub Issue