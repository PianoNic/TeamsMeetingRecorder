#!/bin/bash
set -e

echo "==================================="
echo "Teams Meeting Recorder - Starting"
echo "==================================="

# Disable PC speaker beep
echo "Disabling system beep..."
xset -b 2>/dev/null || true

# Start PulseAudio
echo "Starting PulseAudio..."
pulseaudio --start --exit-idle-time=-1 || true
sleep 2

# Create virtual audio sink
echo "Setting up virtual audio sink..."
pactl load-module module-null-sink sink_name=${PULSEAUDIO_SINK_NAME:-teams_virtual_sink} sink_properties=device.description="Teams_Virtual_Sink" || true

# List audio devices for debugging
echo "Available audio devices:"
pactl list sinks short

# Start Xvfb
echo "Starting Xvfb on display ${DISPLAY:-:99}..."
Xvfb ${DISPLAY:-:99} -screen 0 ${DISPLAY_WIDTH:-1920}x${DISPLAY_HEIGHT:-1080}x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

# Start window manager
echo "Starting Fluxbox window manager..."
fluxbox 2>/dev/null &
sleep 1

echo "==================================="
echo "Services started successfully!"
echo "==================================="
echo "FastAPI: http://localhost:8000"
echo "Swagger Docs: http://localhost:8000/docs"
echo "==================================="

# Execute the main command
exec "$@"
