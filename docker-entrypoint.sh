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

# Wait for the daemon to accept connections before anything talks to it.
for _ in $(seq 1 10); do
    pactl info >/dev/null 2>&1 && break
    sleep 1
done

# Each recording session creates and tears down its own null sink, so no
# shared sink is set up here.

# List audio devices for debugging. Guarded: `set -e` is on, and this is only
# diagnostics - it must never be the reason the container fails to start.
echo "Available audio devices:"
pactl list sinks short || echo "(PulseAudio reported no sinks)"

# Start Xvfb
echo "Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset 2>/dev/null &
XVFB_PID=$!
sleep 2

# Start window manager
echo "Starting Fluxbox window manager..."
fluxbox 2>/dev/null &
sleep 1

echo "Services started successfully!"
echo ""

# Execute the main command
exec "$@"
