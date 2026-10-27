# Changelog — MOSCEYE

## v0.2.1 — 2026-10-26

Mejoras derivadas de `AUDIT_MEJORAS_2026-10-26.md`.

### Integridad y operación
- `mosceye/` ahora es un repositorio git; la integración del simulador quedó
  commiteada en `muse-gadget-sdk` (`mosceye-v0.2.0`). Ver `VERSIONING.md`.
- `.gitignore` excluye entorno virtual, pesos, respaldos, bundle generado y
  evidencia con posibles rostros.
- `run_demo.sh` respeta `MOSCEYE_HOST`/`MOSCEYE_PORT`, avisa si el host no es
  local y usa una sola `BASE_URL`.
- La selección del video es determinista: `principal.mp4` o `MOSCEYE_VIDEO`.
- El servidor rechaza un bind no-loopback sin `MOSCEYE_TOKEN`; con token, los
  clientes remotos deben enviar `Authorization: Bearer …`.
- Los errores del watcher de triggers se registran en
  `$MOSCEYE_RUNTIME_DIR/mosceye_watch.log` (con throttling).

### Robustez
- Watchdog de inferencia: si un request supera `MOSCEYE_INFERENCE_TIMEOUT`
  (30 s por defecto), se publica error y `busy` vuelve a `false`. Un worker
  tardío ya no puede pisar el resultado de un request nuevo.
- El último resultado bueno se restaura tras reiniciar (hasta 24 h) y se marca
  `stale: true`; no se sobrescribe con conteos nulos.
- `configure()` limpia todos los campos derivados, no solo los evidentes.
- `preview.jpg` anota fuera del lock del motor.
- `empty_minutes` se calcula de verdad o se publica `null`; nunca un cero falso.
- `store_calibrated` refleja la calibración real y se añade
  `store_total_available`.
- SAM se desactiva por defecto en CPU (`MOSCEYE_SAM_ON_CPU=1` para forzarlo).

### Contrato y UI
- El mock del skill emite el contrato v2 completo (`--once` incluido), por lo
  que Charm ya no muestra “SIN CONEXION / ULTIMO DATO” con datos falsos.
- `dev_demo.sh` ya no mata procesos ajenos.
- Charm limpia el error local “SIN RESPUESTA” cuando el servidor se recupera.
- Etiquetas más honestas: “CAJA ATENDIDA / CAJA SIN ATENDER” y
  “PERSONAS VISIBLES”.
- Desktop atenúa y anuncia un resultado restaurado como “dato anterior”.

### Evaluación, privacidad y reproducibilidad
- `audit/evaluate.py` + `audit/labels.json`: MAE de personas visibles y
  precisión de caja contra un primer pase visual (pendiente de revisión humana).
- `scripts/redact_evidence.py`: copias con rostros pixelados usando YuNet.
- `scripts/bootstrap.sh`, `requirements.in` y instrucciones de instalación.
- Cabeceras Apache y procedencia de la fuente Montserrat en los archivos
  generados del simulador.
- Documentación consolidada: este changelog, `VERSIONING.md` y el README.
