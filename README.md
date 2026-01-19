# Teams Meeting Recorder Bot

Ein Python-basierter Bot, der automatisch Microsoft Teams-Meetings beitritt und Audio aufzeichnet. Der Bot verwendet FastAPI für die REST-API, Selenium für die Browser-Automatisierung, und VNC für die visuelle Überwachung.

## Features

- **FastAPI REST API**: Einfache HTTP-Endpoints zum Steuern des Bots
- **Automatisches Meeting-Beitreten**: Tritt Teams-Meetings über eine URL bei
- **Audio-Aufnahme**: Hochwertige Audio-Aufnahme mit PulseAudio und sounddevice
- **VNC-Zugriff**: Visuelle Überwachung des Bots über VNC oder noVNC (Web)
- **Docker-basiert**: Vollständig containerisiert mit Docker und Docker Compose
- **Mehrere Sessions**: Unterstützt mehrere gleichzeitige Recording-Sessions
- **Konfigurierbar**: Flexible Konfiguration über Umgebungsvariablen

## Architektur

```
┌─────────────────┐
│   FastAPI       │ ← REST API Endpoints
│   (Port 8000)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Teams Bot      │ ← Selenium WebDriver
│  Controller     │   + Chrome Browser
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
docker compose up -d

# Oder mit Makefile
make build
make up
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

### Makefile-Befehle

```bash
make help          # Zeigt alle verfügbaren Befehle
make build         # Docker Image bauen
make up            # Services starten
make down          # Services stoppen
make logs          # Logs anzeigen
make shell         # Shell im Container öffnen
make clean         # Alles aufräumen
make test-api      # API testen
make healthcheck   # Service-Gesundheit prüfen
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
- **Selenium 4**: Browser-Automatisierung
- **sounddevice**: Audio-Recording mit NumPy
- **PulseAudio**: Virtual Audio Sink
- **Xvfb**: Virtual Display Server
- **x11vnc**: VNC Server
- **Docker**: Containerisierung

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