#!/usr/bin/env bash
# Expose the local API (4000) and voice server (8765) on public https URLs so a
# phone provider (Twilio / Exotel) can reach them, and write the URLs into .env.
# Uses free Cloudflare quick tunnels (no account). The URLs change every run.
#
#   bash scripts/dev-tunnels.sh        then restart the API and voice server
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
LOG_DIR="${TMPDIR:-/tmp}"

start_tunnel() {  # name port -> prints public URL
  local name=$1 port=$2 log="$LOG_DIR/tunnel-$1.log"
  : > "$log"
  nohup cloudflared tunnel --no-autoupdate --url "http://localhost:$port" > "$log" 2>&1 &
  echo $! > "$LOG_DIR/tunnel-$name.pid"
  for _ in $(seq 1 40); do
    url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log" | head -1 || true)
    [ -n "$url" ] && { echo "$url"; return; }
    sleep 1
  done
  echo "tunnel $name did not start; see $log" >&2; exit 1
}

set_env() {  # key value
  if grep -q "^$1=" "$ENV_FILE"; then sed -i "s#^$1=.*#$1=$2#" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}

API_URL=$(start_tunnel api 4000)
VOICE_URL=$(start_tunnel voice 8765)
set_env PUBLIC_API_URL "$API_URL"
set_env PUBLIC_VOICE_URL "$VOICE_URL"

echo "API   : $API_URL"
echo "Voice : $VOICE_URL"
echo "Written to .env. Restart the API and voice server to pick them up."
echo "Stop the tunnels with: kill \$(cat $LOG_DIR/tunnel-*.pid)"
