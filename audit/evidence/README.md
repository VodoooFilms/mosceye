# Evidencia local

Esta carpeta contiene capturas y JSON de validación. **Las imágenes no se
versionan** (`mosceye/.gitignore`) porque las tomas `*-raw.jpg` incluyen rostros
identificables de CCTV.

- Los JSON (`*.json`) sí se versionan: son pequeños y no contienen imágenes.
- Las imágenes permanecen solo en esta Mac.
- Antes de compartir una imagen, genera una copia redactada:

```sh
./mosceye/.venv/bin/python mosceye/scripts/redact_evidence.py mosceye/audit/evidence
```

El script escribe `*-redacted.jpg` y deja los originales intactos. Es una
heurística de detección de rostros: revisa el resultado antes de publicarlo.
