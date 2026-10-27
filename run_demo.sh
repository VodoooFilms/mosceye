#!/bin/sh
# MOSCEYE: reuse a healthy v2 server; never kill unrelated Python/simulator processes.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
PYTHON="$HERE/.venv/bin/python"
HOST=${MOSCEYE_HOST:-127.0.0.1}
PORT=${MOSCEYE_PORT:-8000}
RUNTIME=${MOSCEYE_RUNTIME_DIR:-/tmp}
mkdir -p "$RUNTIME"
HEALTH="$RUNTIME/mosceye_health.json"
SERVICE_LOG="$RUNTIME/mosceye_service.log"
CONNECT_HOST="$HOST"
case "$HOST" in
  0.0.0.0|::|'[::]') CONNECT_HOST=127.0.0.1 ;;
esac
case "$CONNECT_HOST" in
  \[*\]) ;;
  *:*) CONNECT_HOST="[$CONNECT_HOST]" ;;
esac
BASE_URL="http://$CONNECT_HOST:$PORT"
case "$HOST" in
  127.0.0.1|localhost|::1|'[::1]') ;;
  *) echo "Aviso: MOSCEYE_HOST=$HOST no es local; la API requiere MOSCEYE_TOKEN." >&2 ;;
esac
owned_server=''
cleanup() { if [ -n "$owned_server" ]; then kill "$owned_server" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
if curl --fail -s --max-time 2 "$BASE_URL/health" > "$HEALTH"; then
  HEALTH_PATH="$HEALTH" "$PYTHON" -c 'import json,os; s=json.load(open(os.environ["HEALTH_PATH"])); assert s.get("schema_version")==2, "Ese puerto tiene otra versión del servidor. Cierra esa instancia antes de continuar."'
else
  "$PYTHON" "$HERE/sam_service.py" > "$SERVICE_LOG" 2>&1 &
  owned_server=$!
fi
ready=0
for i in $(seq 1 120); do
  if curl -s --max-time 2 "$BASE_URL/health" | "$PYTHON" -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get("ready") else 1)' 2>/dev/null; then
    ready=1; break
  fi
  if [ -n "$owned_server" ] && ! kill -0 "$owned_server" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "El motor no pudo iniciar en $BASE_URL. Revisa $SERVICE_LOG." >&2
  exit 1
fi
cmake --build "$ROOT/muse-gadget-sdk/esp32/simulator/build" --parallel
open "$BASE_URL/desktop" 2>/dev/null || true
"$ROOT/muse-gadget-sdk/esp32/simulator/build/muse_simulator" --retail
