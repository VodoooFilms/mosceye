# Changelog — MOSCEYE

## v0.2.2 — 2026-10-27

### Corrección: segfault del simulador al arrastrar fuera de la ventana
- En la demo en ventana, `muse_simulator --retail` terminó con SIGSEGV tras una
  secuencia de arrastre con coordenadas X negativas (warnings de
  `lv_indev.c:747`).
- Reproducción: se añadió el verbo de escenario `drag=X1,Y1,X2,Y2,STEPS`, que
  genera un arrastre paso a paso con renders intermedios y extremos fuera de
  la ventana. Con ASan/UBSan, 12 variantes de arrastre (fuera por los cuatro
  lados, desde botones, con voz abierta, durante la animación de settle) no
  mostraron errores de memoria en headless: el warning de LVGL por puntos
  fuera de rango es benigno.
- Causa probable: en modo ventana, los eventos del SO entran durante
  `SDL_PumpEvents`, dentro del procesamiento de entrada de LVGL. El event
  watch llamaba ahí mismo a `retail_view_pointer_event`, que muta el árbol
  LVGL (scroll, animaciones, textos) a mitad de ese procesamiento.
- Corrección: el event watch solo encola eventos en una FIFO de 64 con
  coordenadas acotadas a la ventana; la cola se aplica en `render_for`, antes
  de `lv_timer_handler()`, preservando el orden down/move/up. Clamp adicional
  defensivo en `retail_view_pointer_event`.
- Tests: `test_drag_out_of_window_settles_on_store_page` y
  `test_drag_out_right_returns_to_queue_page`. Suite completa: 31/31 y
  `ctest` 1/1.
- Nota: los warnings "X is ... smaller than zero" de LVGL pueden seguir
  apareciendo al arrastrar fuera; provienen del driver SDL vendorizado de
  LVGL, que solo registra el aviso. Nuestros manejadores ya nunca reciben
  coordenadas fuera de rango ni se ejecutan dentro del procesamiento de
  entrada.

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
