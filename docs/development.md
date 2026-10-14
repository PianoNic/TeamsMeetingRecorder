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

### Diagrams

The diagrams are drawn with [D2](https://d2lang.com) and committed as SVG, so they look the same on this site and on GitHub. Each exists twice, light and dark; the page shows the one matching the theme. The sources are in `docs/diagrams/src`. After editing one, render both versions (the overview and microphone diagrams use the ELK layout):

```bash
cd docs/diagrams
d2 --pad 24 --layout elk src/overview.d2 overview.svg
d2 --pad 24 --layout elk --theme 200 src/overview-dark.d2 overview-dark.svg
d2 --pad 24 --dagre-nodesep 30 src/lifecycle.d2 lifecycle.svg
d2 --pad 24 --dagre-nodesep 30 --theme 200 src/lifecycle-dark.d2 lifecycle-dark.svg
d2 --pad 24 --layout elk --elk-padding "[top=30,left=30,bottom=30,right=30]" src/microphone.d2 microphone.svg
d2 --pad 24 --layout elk --elk-padding "[top=30,left=30,bottom=30,right=30]" --theme 200 src/microphone-dark.d2 microphone-dark.svg
```

To try a change quickly, paste a source into [play.d2lang.com](https://play.d2lang.com).

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
