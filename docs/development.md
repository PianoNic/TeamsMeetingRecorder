# Development

## Running from source

The bot needs Linux with PulseAudio, Xvfb and Chromium, which is why the image is the easiest way to run it. To work on it locally, build the image from the checkout:

```bash
docker build -t teams-recorder:dev .
docker run --rm -p 8000:8000 --shm-size=2gb --init teams-recorder:dev
```

## Tests

The tests fake PulseAudio, the browser and `parec`, so they run anywhere Python runs:

```bash
pip install -r requirements.txt pytest httpx
python -m pytest tests/
```
