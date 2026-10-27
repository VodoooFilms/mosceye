#!/bin/sh
# MOSCEYE: reuse a healthy v2 server; never kill unrelated Python/simulator processes.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
PYTHON="$HERE/.venv/bin/python"
owned_server=''
cleanup() { if [ -n "$owned_server" ]; then kill "$owned_server" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
if curl --fail -s --max-time 2 http://127.0.0.1:8000/health > /tmp/mosceye_health.json; then
  "$PYTHON" -c 'import json; s=json.load(open("/tmp/mosceye_health.json")); assert s.get("schema_version")==2, "El puerto 8000 tiene otra versión del servidor. Cierra esa instancia antes de continuar."'
else
  "$PYTHON" "$HERE/sam_service.py" > /tmp/mosceye_service.log 2>&1 &
  owned_server=$!
fi
ready=0
for i in $(seq 1 120); do
  if curl -s --max-time 2 http://127.0.0.1:8000/health | "$PYTHON" -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get("ready") else 1)' 2>/dev/null; then
    ready=1; break
  fi
  if [ -n "$owned_server" ] && ! kill -0 "$owned_server" 2>/dev/null; then break; fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo 'El motor no pudo iniciar. Revisa /tmp/mosceye_service.log.' >&2
  exit 1
fi
cmake --build "$ROOT/muse-gadget-sdk/esp32/simulator/build" --parallel
open 'http://127.0.0.1:8000/desktop' 2>/dev/null || true
"$ROOT/muse-gadget-sdk/esp32/simulator/build/muse_simulator" --retail
