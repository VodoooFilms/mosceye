#!/bin/sh
# Reproducible MOSCEYE setup on a clean macOS machine.
#
#   ./mosceye/scripts/bootstrap.sh              # Python environment + simulator
#   ./mosceye/scripts/bootstrap.sh --sam        # also download the SAM checkpoint
#   ./mosceye/scripts/bootstrap.sh --python-only
#
# The checkpoint is 358 MB and is not stored in git.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
PYTHON=${PYTHON:-python3}
VENV="$HERE/.venv"
SAM_PATH="$HERE/checkpoints/sam_vit_b_01ec64.pth"
SAM_URL=${MOSCEYE_SAM_URL:-https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth}
SAM_SHA256="ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912"
WANT_SAM=0
PYTHON_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --sam) WANT_SAM=1 ;;
    --python-only) PYTHON_ONLY=1 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Se requiere Python 3.11 o superior."'
if [ ! -x "$VENV/bin/python" ]; then
  echo "Creando entorno virtual en $VENV…"
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$HERE/requirements.txt"

if [ "$WANT_SAM" -eq 1 ]; then
  mkdir -p "$HERE/checkpoints"
  if [ -f "$SAM_PATH" ]; then
    echo "Checkpoint SAM ya presente."
  else
    echo "Descargando checkpoint SAM (358 MB)…"
    tmp="$SAM_PATH.part"
    curl -L --fail --progress-bar -o "$tmp" "$SAM_URL"
    mv "$tmp" "$SAM_PATH"
  fi
  actual=$(shasum -a 256 "$SAM_PATH" | awk '{print $1}')
  if [ "$actual" != "$SAM_SHA256" ]; then
    echo "SHA-256 inesperado para $SAM_PATH" >&2
    echo "  esperado: $SAM_SHA256" >&2
    echo "  obtenido: $actual" >&2
    exit 1
  fi
  echo "Checkpoint SAM verificado."
fi

if [ "$PYTHON_ONLY" -eq 0 ]; then
  if ! command -v cmake >/dev/null 2>&1; then
    echo "Falta cmake. Instálalo con: brew install cmake ninja" >&2
    exit 1
  fi
  echo "Configurando el simulador…"
  cmake -S "$ROOT/muse-gadget-sdk/esp32/simulator" \
        -B "$ROOT/muse-gadget-sdk/esp32/simulator/build" \
        -G Ninja -DCMAKE_BUILD_TYPE=Debug
  cmake --build "$ROOT/muse-gadget-sdk/esp32/simulator/build" --parallel
fi

echo
echo "Listo. Arranca con:"
echo "  ./mosceye/run_demo.sh"
echo "Sin checkpoint SAM el conteo funciona; los contornos quedan desactivados."
