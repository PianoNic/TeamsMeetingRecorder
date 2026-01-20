# Quick Start Guide - Teams Meeting Recorder

Schnellstart-Anleitung um in 5 Minuten loszulegen! 🚀

## Voraussetzungen

- Docker (≥ 20.10) mit Compose v2
- 2GB freier RAM
- Internetzugang

## Installation (3 Schritte)

### 1. Repository klonen

```bash
git clone <repository-url>
cd TeamsMeetingRecorder
```

### 2. Services starten

```bash
# Mit Docker Compose v2
docker compose build
docker compose up -d
```

Das war's! Die Services laufen jetzt:

- ✅ **API**: http://localhost:8000
- ✅ **Swagger Docs**: http://localhost:8000/docs
- ✅ **noVNC Web**: http://localhost:8080
- ✅ **VNC**: localhost:5900

### 3. Ersten Bot starten

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "DEINE_TEAMS_URL",
    "display_name": "Recording Bot",
    "record_audio": true,
    "max_duration_minutes": 30
  }'
```

**Response:**
```json
{
  "success": true,
  "session": {
    "session_id": "abc-123-def",
    "status": "joining"
  }
}
```

## Bot überwachen

### Option 1: Web Interface (noVNC)

Öffne http://localhost:8080 im Browser und sehe live, was der Bot macht!

### Option 2: Status API

```bash
# Ersetze SESSION_ID mit deiner ID
curl http://localhost:8000/status/SESSION_ID
```

### Option 3: Logs

```bash
docker compose logs -f teams-recorder

# ODER
make logs
```

## Recording stoppen

```bash
curl -X POST http://localhost:8000/stop/SESSION_ID
```

## Recording herunterladen

```bash
curl -O http://localhost:8000/download/SESSION_ID
```

Die Datei wird auch hier gespeichert:
```
./recordings/SESSION_ID_TIMESTAMP.wav
```

## Nützliche Befehle

```bash
docker compose ps                    # Service-Status anzeigen
docker compose logs -f               # Logs anschauen
docker compose exec teams-recorder bash  # Shell im Container öffnen
docker compose down -v               # Alles aufräumen
```

## Troubleshooting

### Services starten nicht

```bash
# Status prüfen
docker compose ps

# Logs checken
docker compose logs
```

### Bot kann nicht beitreten

1. Prüfe die Teams-URL
2. Schaue über noVNC zu: http://localhost:8080
3. Checke die Logs: `docker compose logs -f`

### Port bereits belegt

Ändere die Ports in `compose.yaml`:

```yaml
ports:
  - "8001:8000"  # Statt 8000
  - "5901:5900"  # Statt 5900
  - "8081:8080"  # Statt 8080
```

## Nächste Schritte

- 📖 Lies das vollständige [README.md](README.md)
- 🔧 Siehe [API_EXAMPLES.md](API_EXAMPLES.md) für Code-Beispiele
- ⚙️ Konfiguriere über `.env` (siehe `.env.example`)

## Python-Client (Quick)

```python
import requests

# Meeting beitreten
response = requests.post("http://localhost:8000/join", json={
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Bot",
    "record_audio": True
})

session_id = response.json()["session"]["session_id"]
print(f"Session: {session_id}")

# Status prüfen
status = requests.get(f"http://localhost:8000/status/{session_id}").json()
print(f"Status: {status['status']}")
```

## Wichtige Hinweise

⚠️ **Datenschutz**: Hole immer die Einwilligung aller Teilnehmer ein!

🔒 **Sicherheit**: Nutze VNC-Passwort (`teams123`) nur für Tests. Ändere es für Produktion!

📁 **Recordings**: Werden in `./recordings/` gespeichert

📝 **Logs**: Werden in `./logs/` gespeichert

## Support

- Swagger UI: http://localhost:8000/docs
- Vollständige Docs: [README.md](README.md)
- API Beispiele: [API_EXAMPLES.md](API_EXAMPLES.md)

Viel Erfolg! 🎉
