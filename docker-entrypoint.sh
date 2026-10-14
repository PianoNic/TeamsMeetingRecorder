#!/bin/bash
set -e

cat <<'EOF'

 _____                           __  __           _   _               ____                        _
|_   _|__  __ _ _ __ ___   ___  |  \/  | ___  ___| |_(_)_ __   __ _  |  _ \ ___  ___ ___  _ __ __| | ___ _ __
  | |/ _ \/ _` | '_ ` _ \ / __| | |\/| |/ _ \/ _ \ __| | '_ \ / _` | | |_) / _ \/ __/ _ \| '__/ _` |/ _ \ '__|
  | |  __/ (_| | | | | | |\__ \ | |  | |  __/  __/ |_| | | | | (_| | |  _ <  __/ (_| (_) | | | (_| |  __/ |
  |_|\___|\__,_|_| |_| |_||___/ |_|  |_|\___|\___|\__|_|_| |_|\__, | |_| \_\___|\___\___/|_|  \__,_|\___|_|
                                                               |___/
                                                By PianoNic
                                                
EOF

# Disable PC speaker beep
echo "Disabling system beep..."
xset -b 2>/dev/null || true

# Start PulseAudio. Runtime state survives in the container filesystem across a
# `docker start`, and a stale socket stops the daemon coming back up, so clear it
# first - otherwise restarting a container that has run before never recovers.
echo "Starting PulseAudio..."
rm -rf /tmp/pulse-* "${HOME:-/home/botuser}/.config/pulse" 2>/dev/null || true
pulseaudio --start --exit-idle-time=-1 || true

# Wait for the daemon to accept connections before anything talks to it. A host
# that starts several containers at once can be slow here, so allow a minute and
# say how long it took.
STARTUP_WAIT="${STARTUP_WAIT_SECONDS:-60}"
waited=0
until pactl info >/dev/null 2>&1 || [ "$waited" -ge "$STARTUP_WAIT" ]; do
    sleep 1
    waited=$((waited + 1))
done
if pactl info >/dev/null 2>&1; then
    echo "PulseAudio is up after ${waited}s"
else
    echo "WARNING: PulseAudio not reachable after ${waited}s, recordings will fail until it is"
fi

# Each recording session creates and tears down its own null sink, so no
# shared sink is set up here.

# List audio devices for debugging. Guarded: `set -e` is on, and this is only
# diagnostics - it must never be the reason the container fails to start.
echo "Available audio devices:"
pactl list sinks short || echo "(PulseAudio reported no sinks)"

# Start Xvfb. Its lock file and socket survive a restart exactly like PulseAudio's
# runtime state, and a stale lock makes Xvfb refuse to start ("server already
# running"). The container would still answer the health check while every
# browser launch failed with "Missing X server or $DISPLAY", so clear them first.
echo "Starting Xvfb on display :99..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
# Its own messages stay visible: when it fails, they say why.
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Do not continue until the display actually accepts connections.
waited=0
until xset -q -display :99 >/dev/null 2>&1 || [ "$waited" -ge "$STARTUP_WAIT" ]; do
    if ! kill -0 "$XVFB_PID" 2>/dev/null; then
        # Printed to stdout as well: some hosts only keep stdout of a container that
        # dies during startup, and this line is the only clue to why it did.
        echo "FATAL: Xvfb exited during startup after ${waited}s - a browser could never launch."
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done
if ! xset -q -display :99 >/dev/null 2>&1; then
    echo "FATAL: Xvfb did not accept connections on :99 within ${STARTUP_WAIT}s - a browser could never launch."
    exit 1
fi
echo "Xvfb is up on :99 after ${waited}s"

# Start window manager
echo "Starting Fluxbox window manager..."
fluxbox 2>/dev/null &
sleep 1

echo "Services started successfully!"
echo ""

# Execute the main command
exec "$@"
