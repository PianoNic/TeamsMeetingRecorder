# Development

## Running from source

The bot needs Linux with PulseAudio, Xvfb and Chromium, so the container is the easiest way to run your checkout too:

```bash
docker build -t teams-recorder:dev .
docker run --rm -p 8000:8000 --shm-size=2gb --init teams-recorder:dev
```

To watch what the browser does, start a meeting of your own, send the bot in, and follow the log: every step from opening the link to leaving is logged with its session id.

## Tests

The tests fake PulseAudio, the browser and `parec`, so they run anywhere Python runs:

```bash
pip install -r requirements.txt pytest httpx2
python -m pytest tests/
```

`tests/test_openapi_docs.py` fails when the published API schema no longer matches the code, see [The API reference](#the-api-reference).

## Project layout

| Path | What is in it |
|---|---|
| `app/main.py` | The HTTP API and the app's start and shutdown |
| `app/bot.py` | One session: browser, joining, lobby, watching the call, leaving |
| `app/recorder.py` | Reading the session's audio device into a WAV or FLAC file |
| `app/audio_out.py` | The microphone: playback, uploads and live ingest |
| `app/storage.py` | Local, Azure Blob and S3 backends |
| `app/journal.py`, `app/recovery.py` | Surviving a restart in the middle of a session |
| `app/outbox.py`, `app/webhook.py` | Webhooks that are retried until they arrive |
| `app/config.py` | All settings |
| `docker-entrypoint.sh` | Starts PulseAudio, the virtual display and the window manager before the app |
| `docs/` | This site |

## The docs site

The site is built with [VitePress](https://vitepress.dev) from the markdown in `docs/`, which is self-contained with its own `package.json`:

```bash
cd docs
bun install      # or npm install
bun run dev      # live preview at http://localhost:5173
bun run build    # static site in docs/.vitepress/dist
```

It is hosted as a static site: Cloudflare Pages builds it from the repository with root directory `docs`, build command `bun run build` and output directory `.vitepress/dist`.

### The API reference

The pages under *API reference* are generated from `docs/public/openapi.json` by [vitepress-openapi](https://github.com/enzonotario/vitepress-openapi). After changing an endpoint, refresh the file from the code:

```bash
python -c "import json; from app.main import app; json.dump(app.openapi(), open('docs/public/openapi.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)"
```

The test suite checks that the file matches the code, so a forgotten refresh fails the build instead of publishing an outdated reference.

## Releasing

Releases are drafted automatically: every merged pull request lands in the next release's notes, sorted by its label.

| Label | Section in the release notes |
|---|---|
| `feature` | Features |
| `enhancement` | Enhancements |
| `refactor` | Refactors |
| `bug` | Bug fixes |

So every pull request gets exactly one of these labels, and closes an issue that describes the problem it solves.

Publishing the drafted release on GitHub builds the image for x86-64 and ARM64 and pushes it to GitHub Container Registry and Docker Hub, tagged with the version, the major and minor version, and `latest`. The version in `application.properties` is updated by the release itself.
