# API Examples - Teams Meeting Recorder

Dieses Dokument enthält praktische Beispiele für die Verwendung der Teams Meeting Recorder API.

## cURL Beispiele

### 1. Meeting beitreten und Recording starten

```bash
curl -X POST http://localhost:8000/join \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/19%3ameeting_...",
    "display_name": "Recording Bot",
    "record_audio": true,
    "max_duration_minutes": 60
  }'
```

### 2. Status einer Session abfragen

```bash
curl http://localhost:8000/status/abc-123-def-456
```

### 3. Alle aktiven Sessions auflisten

```bash
curl http://localhost:8000/sessions | jq '.'
```

### 4. Recording stoppen

```bash
curl -X POST http://localhost:8000/stop/abc-123-def-456
```

### 5. Recording herunterladen

```bash
curl -O http://localhost:8000/download/abc-123-def-456
```

### 6. Session löschen

```bash
curl -X DELETE http://localhost:8000/session/abc-123-def-456
```

## Python Beispiele

### Einfaches Beispiel

```python
import requests
import time

API_URL = "http://localhost:8000"

# Meeting beitreten
response = requests.post(f"{API_URL}/join", json={
    "meeting_url": "https://teams.microsoft.com/l/meetup-join/...",
    "display_name": "Bot Recorder",
    "record_audio": True,
    "max_duration_minutes": 30
})

if response.status_code == 200:
    session_id = response.json()["session"]["session_id"]
    print(f"✓ Session gestartet: {session_id}")

    # Warte 30 Minuten oder stoppe manuell
    time.sleep(1800)

    # Recording stoppen
    stop_response = requests.post(f"{API_URL}/stop/{session_id}")
    print(f"✓ Recording gestoppt: {stop_response.json()['message']}")
```

### Vollständiges Beispiel mit Status-Polling

```python
import requests
import time
from typing import Optional

class TeamsRecorderClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session_id: Optional[str] = None

    def start_recording(self, meeting_url: str, display_name: str,
                       max_duration_minutes: Optional[int] = None) -> dict:
        """Starte eine neue Recording-Session."""
        response = requests.post(f"{self.base_url}/join", json={
            "meeting_url": meeting_url,
            "display_name": display_name,
            "record_audio": True,
            "max_duration_minutes": max_duration_minutes
        })
        response.raise_for_status()

        data = response.json()
        self.session_id = data["session"]["session_id"]
        return data

    def get_status(self, session_id: Optional[str] = None) -> dict:
        """Hole den Status einer Session."""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("Keine Session ID angegeben")

        response = requests.get(f"{self.base_url}/status/{sid}")
        response.raise_for_status()
        return response.json()

    def stop_recording(self, session_id: Optional[str] = None) -> dict:
        """Stoppe eine Recording-Session."""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("Keine Session ID angegeben")

        response = requests.post(f"{self.base_url}/stop/{sid}")
        response.raise_for_status()
        return response.json()

    def download_recording(self, session_id: Optional[str] = None,
                          output_path: str = "recording.wav"):
        """Lade die Aufnahme herunter."""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("Keine Session ID angegeben")

        response = requests.get(f"{self.base_url}/download/{sid}")
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        return output_path

    def wait_for_status(self, target_status: str, timeout: int = 300,
                       session_id: Optional[str] = None):
        """Warte bis die Session einen bestimmten Status erreicht."""
        sid = session_id or self.session_id
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_status(sid)
            if status["status"] == target_status:
                return status
            time.sleep(5)

        raise TimeoutError(f"Status '{target_status}' nicht erreicht nach {timeout}s")


# Verwendung
if __name__ == "__main__":
    client = TeamsRecorderClient()

    # Meeting beitreten
    result = client.start_recording(
        meeting_url="https://teams.microsoft.com/l/meetup-join/...",
        display_name="Recording Bot",
        max_duration_minutes=60
    )
    print(f"Session gestartet: {result['session']['session_id']}")

    # Warte bis Recording läuft
    try:
        status = client.wait_for_status("recording", timeout=120)
        print(f"Recording läuft seit {status['uptime_seconds']}s")
    except TimeoutError as e:
        print(f"Fehler: {e}")

    # Überwache das Recording
    for i in range(10):
        time.sleep(30)  # Alle 30 Sekunden
        status = client.get_status()
        print(f"Status: {status['status']}, Dauer: {status['recording_duration_seconds']:.1f}s")

    # Recording stoppen
    result = client.stop_recording()
    print(f"Recording gestoppt: {result['message']}")

    # Aufnahme herunterladen
    filepath = client.download_recording(output_path="meeting_recording.wav")
    print(f"Aufnahme gespeichert: {filepath}")
```

### Async Beispiel mit asyncio

```python
import asyncio
import httpx

async def record_meeting(meeting_url: str, duration_minutes: int = 30):
    """Async Meeting-Recording."""
    async with httpx.AsyncClient() as client:
        # Meeting beitreten
        response = await client.post("http://localhost:8000/join", json={
            "meeting_url": meeting_url,
            "display_name": "Async Bot",
            "record_audio": True,
            "max_duration_minutes": duration_minutes
        })
        session_id = response.json()["session"]["session_id"]
        print(f"Session {session_id} gestartet")

        # Warte auf Completion (oder bis max_duration erreicht)
        for i in range(duration_minutes * 2):  # Alle 30 Sekunden prüfen
            await asyncio.sleep(30)
            status_response = await client.get(f"http://localhost:8000/status/{session_id}")
            status = status_response.json()

            if status["status"] in ["stopped", "error"]:
                print(f"Session beendet: {status['status']}")
                break

            print(f"Recording läuft: {status['recording_duration_seconds']:.1f}s")

        return session_id

# Mehrere Meetings parallel aufnehmen
async def main():
    meetings = [
        "https://teams.microsoft.com/l/meetup-join/meeting1...",
        "https://teams.microsoft.com/l/meetup-join/meeting2...",
        "https://teams.microsoft.com/l/meetup-join/meeting3..."
    ]

    tasks = [record_meeting(url, duration_minutes=60) for url in meetings]
    session_ids = await asyncio.gather(*tasks)

    print(f"Alle Sessions abgeschlossen: {session_ids}")

if __name__ == "__main__":
    asyncio.run(main())
```

## JavaScript/Node.js Beispiele

### Einfaches Beispiel

```javascript
const axios = require('axios');

const API_URL = 'http://localhost:8000';

async function recordMeeting(meetingUrl, displayName, durationMinutes = 30) {
  try {
    // Meeting beitreten
    const joinResponse = await axios.post(`${API_URL}/join`, {
      meeting_url: meetingUrl,
      display_name: displayName,
      record_audio: true,
      max_duration_minutes: durationMinutes
    });

    const sessionId = joinResponse.data.session.session_id;
    console.log(`✓ Session gestartet: ${sessionId}`);

    // Status polling
    const checkInterval = setInterval(async () => {
      const statusResponse = await axios.get(`${API_URL}/status/${sessionId}`);
      const status = statusResponse.data;

      console.log(`Status: ${status.status}, Dauer: ${status.recording_duration_seconds}s`);

      if (status.status === 'stopped' || status.status === 'error') {
        clearInterval(checkInterval);
        console.log('Recording beendet');
      }
    }, 30000); // Alle 30 Sekunden

    return sessionId;

  } catch (error) {
    console.error('Fehler:', error.response?.data || error.message);
    throw error;
  }
}

// Verwendung
recordMeeting(
  'https://teams.microsoft.com/l/meetup-join/...',
  'Node Bot',
  60
).then(sessionId => {
  console.log(`Recording mit Session ${sessionId} läuft`);
}).catch(err => {
  console.error('Fehler beim Starten:', err);
});
```

## Shell Script Beispiel

```bash
#!/bin/bash

API_URL="http://localhost:8000"
MEETING_URL="https://teams.microsoft.com/l/meetup-join/..."
DISPLAY_NAME="Shell Bot"
DURATION=60

# Meeting beitreten
echo "Starte Recording..."
RESPONSE=$(curl -s -X POST "$API_URL/join" \
  -H "Content-Type: application/json" \
  -d "{
    \"meeting_url\": \"$MEETING_URL\",
    \"display_name\": \"$DISPLAY_NAME\",
    \"record_audio\": true,
    \"max_duration_minutes\": $DURATION
  }")

SESSION_ID=$(echo $RESPONSE | jq -r '.session.session_id')
echo "Session ID: $SESSION_ID"

# Status monitoring
while true; do
  sleep 30
  STATUS=$(curl -s "$API_URL/status/$SESSION_ID" | jq -r '.status')
  DURATION=$(curl -s "$API_URL/status/$SESSION_ID" | jq -r '.recording_duration_seconds')

  echo "Status: $STATUS, Dauer: ${DURATION}s"

  if [ "$STATUS" = "stopped" ] || [ "$STATUS" = "error" ]; then
    echo "Recording beendet"
    break
  fi
done

# Download recording
echo "Lade Recording herunter..."
curl -o "recording_${SESSION_ID}.wav" "$API_URL/download/$SESSION_ID"
echo "✓ Fertig: recording_${SESSION_ID}.wav"
```

## Swagger UI

Die interaktive API-Dokumentation ist verfügbar unter:

**http://localhost:8000/docs**

Dort kannst du:
- Alle Endpoints sehen
- Requests direkt aus dem Browser testen
- Die Response-Schemas erkunden
- Beispiel-Requests generieren

## Tipps

### 1. Error Handling

Immer auf HTTP-Status-Codes achten:

```python
try:
    response = requests.post(f"{API_URL}/join", json=data)
    response.raise_for_status()  # Wirft Exception bei 4xx/5xx
except requests.exceptions.HTTPError as e:
    print(f"HTTP Fehler: {e.response.status_code}")
    print(f"Details: {e.response.json()}")
```

### 2. Session Management

Sessions werden im Memory gespeichert. Bei Container-Restart gehen sie verloren!

```python
# Speichere Session IDs persistent
import json

def save_session_id(session_id: str):
    with open('sessions.json', 'a') as f:
        json.dump({"session_id": session_id, "timestamp": time.time()}, f)
        f.write('\n')
```

### 3. Health Check

Prüfe ob die API läuft:

```bash
curl http://localhost:8000/
# {"name":"Teams Meeting Recorder API","version":"1.0.0","status":"running","active_sessions":0}
```

### 4. VNC Monitoring

Überwache den Bot visuell über noVNC:

```bash
# Öffne im Browser
open http://localhost:8080
```

## Troubleshooting

### API antwortet nicht

```bash
# Prüfe Container Status
docker compose ps

# Prüfe Logs
docker compose logs teams-recorder
```

### Session nicht gefunden (404)

Die Session wurde bereits gestoppt oder der Container wurde neugestartet.

### Recording-Datei nicht verfügbar

Warte bis das Recording komplett gestoppt ist (`status: "stopped"`).
