#!/usr/bin/env python3
"""Create face-redacted copies of evidence images before sharing them.

Uses OpenCV's YuNet face detector. The model is downloaded once into
``mosceye/checkpoints/`` and verified against a fixed SHA-256. Originals are
never modified; copies are written as ``<name>-redacted.jpg``.

    ./mosceye/.venv/bin/python mosceye/scripts/redact_evidence.py mosceye/audit/evidence
    ./mosceye/.venv/bin/python mosceye/scripts/redact_evidence.py --overwrite DIR

A face detector is a heuristic: review the output before publishing.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

import cv2

EXTENSIONS = {".jpg", ".jpeg", ".png"}
MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
DEFAULT_MODEL = Path(__file__).resolve().parents[1] / "checkpoints" / "face_detection_yunet_2023mar.onnx"


def ensure_model(path: Path) -> Path:
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == MODEL_SHA256:
            return path
        raise SystemExit(f"{path} no coincide con el SHA-256 esperado ({digest}).")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    print(f"Descargando modelo de detección de rostros en {path}…", file=sys.stderr)
    try:
        try:
            urllib.request.urlretrieve(MODEL_URL, tmp)
        except OSError as error:
            raise SystemExit(f"No se pudo descargar el modelo de rostros: {error}") from error
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise SystemExit(f"El modelo descargado no coincide con el SHA-256 esperado ({digest}).")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def pixelate(image, x, y, w, h, blocks: int = 8) -> None:
    pad = max(6, int(0.25 * max(w, h)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(image.shape[1], x + w + pad), min(image.shape[0], y + h + pad)
    if x1 <= x0 or y1 <= y0:
        return
    region = image[y0:y1, x0:x1]
    small = cv2.resize(region, (max(1, (x1 - x0) // blocks), max(1, (y1 - y0) // blocks)),
                       interpolation=cv2.INTER_LINEAR)
    image[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)


def redact(path: Path, detector, overwrite: bool) -> tuple[int, Path]:
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"no se pudo leer {path}")
    height, width = image.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    count = 0 if faces is None else len(faces)
    for face in faces if faces is not None else []:
        x, y, w, h = (int(v) for v in face[:4])
        pixelate(image, x, y, w, h)
    target = path if overwrite else path.with_name(f"{path.stem}-redacted.jpg")
    if not cv2.imwrite(str(target), image):
        raise RuntimeError(f"no se pudo escribir {target}")
    return count, target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--overwrite", action="store_true", help="replace originals (destructive)")
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error(f"{args.directory} no es un directorio")
    if args.overwrite:
        print("Aviso: --overwrite destruye los originales.", file=sys.stderr)

    model = ensure_model(args.model)
    # The input size is set per image; this placeholder is replaced in redact().
    detector = cv2.FaceDetectorYN_create(str(model), "", (320, 320), 0.6, 0.3, 5000)

    files = sorted(p for p in args.directory.rglob("*") if p.suffix.lower() in EXTENSIONS
                   and not p.stem.endswith("-redacted"))
    total_faces = 0
    for path in files:
        try:
            faces, target = redact(path, detector, args.overwrite)
        except RuntimeError as error:
            print(f"ERROR {path}: {error}", file=sys.stderr)
            continue
        total_faces += faces
        print(f"{path} -> {target} ({faces} rostros)")
    print(f"{len(files)} imágenes, {total_faces} rostros redactados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
