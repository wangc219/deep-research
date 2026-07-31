#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:99}"
RUNTIME_ROOT="${CRAWLER_RUNTIME_ROOT:-/workspace/runtime}"
mkdir -p "$RUNTIME_ROOT" "$RUNTIME_ROOT/sessions"

Xvfb "$DISPLAY" -screen 0 1440x900x24 -ac +extension GLX +render -noreset &
openbox-session >/tmp/openbox.log 2>&1 &
x11vnc \
  -display "$DISPLAY" \
  -forever \
  -shared \
  -nopw \
  -rfbport 5900 \
  -listen 0.0.0.0 \
  >/tmp/x11vnc.log 2>&1 &

echo "noVNC is available at http://localhost:7900/vnc.html"
exec websockify --web=/usr/share/novnc 0.0.0.0:7900 localhost:5900
