#!/usr/bin/env sh
set -e

PORT="${PORT:-8080}"

mkdir -p /app/keys

# ---- TTS credentials JSON (try multiple env names) ----
TTS_JSON="${GOOGLE_TTS_CREDENTIALS_JSON:-${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}}"
if [ -n "${TTS_JSON:-}" ]; then
  echo "$TTS_JSON" > /app/keys/tts.json
  export GOOGLE_APPLICATION_CREDENTIALS="/app/keys/tts.json"
fi

# ---- STT credentials JSON ----
STT_JSON="${GOOGLE_STT_CREDENTIALS_JSON:-}"
if [ -n "${STT_JSON:-}" ]; then
  echo "$STT_JSON" > /app/keys/stt.json
  export GOOGLE_STT_CREDENTIALS="/app/keys/stt.json"
fi

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips="*"
