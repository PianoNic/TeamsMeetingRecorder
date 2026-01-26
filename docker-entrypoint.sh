#!/bin/bash
set -e

cat <<'EOF'

 _____                      __  __           _   _               ____                         _
|_   _|__  __ _ _ __ ___   |  \/  | ___  ___| |_(_)_ __   __ _  |  _ \ ___  ___ ___  _ __ __| | ___ _ __
  | |/ _ \/ _` | '_ ` _ \  | |\/| |/ _ \/ _ \ __| | '_ \ / _` | | |_) / _ \/ __/ _ \| '__/ _` |/ _ \ '__|
  | |  __/ (_| | | | | | | | |  | |  __/  __/ |_| | | | | (_| | |  _ <  __/ (_| (_) | | | (_| |  __/ |
  |_|\___|\__,_|_| |_| |_| |_|  |_|\___|\___|\__|_|_| |_|\__, | |_| \_\___|\___\___/|_|  \__,_|\___|_|
                                                          |___/
                                                By PianoNic
                                                
EOF

# Disable PC speaker beep
echo "Disabling system beep..."
xset -b 2>/dev/null || true

# Start PulseAudio
echo "Starting PulseAudio..."
pulseaudio --start --exit-idle-time=-1 || true

# Create virtual audio sink
echo "Setting up virtual audio sink..."
pactl load-module module-null-sink sink_name=teams_virtual_sink sink_properties=device.description="Teams_Virtual_Sink" || true

# List audio devices for debugging
echo "Available audio devices:"
pactl list sinks short

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
