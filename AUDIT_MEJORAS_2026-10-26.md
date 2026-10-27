# Auditoría MOSCEYE — Hallazgos y mejoras

**Fecha:** 2026-10-26
**Alcance:** revisión de solo lectura de todo el proyecto (`mosceye/` + integración `muse-gadget-sdk/`), de los informes recientes y de la evidencia. No se modificó código.
**Estado verificado:** 23/23 tests Python OK · `ctest` del simulador 1/1 OK · sin servidor en ejecución durante la revisión.

---

## 1. Resumen ejecutivo

El núcleo v2 está bien diseñado y probado: un solo productor de frames, admisión de un request a la vez, detección semántica primero y SAM solo para contornos, publicación atómica en `/tmp`, y una UI que distingue “desconocido” de “cero”. La documentación es inusualmente honesta sobre los límites.

Los riesgos principales no están en el algoritmo, sino en **la operación y la integridad del proyecto**:

1. **No hay control de versiones.** El proyecto puede perderse con un `git clean` accidental. Es el hallazgo más grave y lleva señalado en varios informes sin corregirse.
2. **La ruta “mock/skill” está rota respecto al contrato v2** y su lanzador mata procesos ajenos, justo lo que el diseño v2 prohíbe.
3. **Hay un bug real de UX en Charm:** el error local “SIN RESPUESTA. REINTENTA.” puede quedarse pegado aunque el servidor se recupere.
4. **El servidor puede quedarse `busy=True` para siempre** si una inferencia se cuelga; no hay watchdog.
5. **Se pierde el último resultado al reiniciar** y se sobrescribe con conteos nulos.

Nada de esto exige rediseñar el núcleo. Son correcciones acotadas.

---

## 2. Hallazgos priorizados

### CRÍTICO

#### C1. El proyecto no está versionado y es vulnerable a pérdida total
**Evidencia**
- La raíz `/Users/antoin/Documents/META HACck` **no es un repositorio git** (`fatal: not a git repository`).
- En `muse-gadget-sdk` (rama `main`) están **sin seguimiento**: `esp32/simulator/src/retail_view.c`, `retail_voice.c`, `retail_voice.h`, `retail_voice.m`, `mosceye_logo.c`, `retail_number_font.c`, `Info.plist` y `skills/retail-tracker/`.
- **Modificados sin commit**: `esp32/simulator/CMakeLists.txt` y `esp32/simulator/src/main.c`.
- Varios informes ya lo advirtieron y sigue igual.

**Impacto:** un `git clean -fdx`, un cambio de rama o un `git checkout` en el SDK borra la UI, la voz y el skill. No hay forma de volver a un estado conocido.

**Corrección propuesta**
1. `git init` en la raíz (o repo dedicado que incluya `mosceye/` y los archivos del SDK), con `.gitignore` para `.venv/`, `checkpoints/`, `*.mp4`, `build/`, `__pycache__/`, `backups/` y evidencia cruda.
2. Primer commit con **todo** el código fuente, incluidos los archivos hoy untracked.
3. Copia externa (Time Machine / disco) de `checkpoints/`, footage y evidencia: no deben depender de git.
4. Etiquetar el estado actual (`git tag v0.2.0`) antes de tocar nada.

---

### ALTO

#### H1. El mock y el skill `retail-tracker` son incompatibles con el contrato v2
**Evidencia**
- `skills/retail-tracker/mock_retail_data.py` emite solo `{people_in_queue, cashier_present, empty_minutes}`.
- Charm v2 exige `published_epoch`, `counts_ready`, `people_in_store`, `zones_calibrated`, `request_id`, `phase`, etc. (`retail_view.c`, `refresh()`).
- Resultado: con el mock, Charm muestra **“SIN CONEXION / ULTIMO DATO”** y ningún número.
- `skills/retail-tracker/SKILL.md` y `README.md` describen la UI negra y el contrato antiguo.
- `skills/retail-tracker/dev_demo.sh` hace `pkill -f muse_simulator` y `pkill -f mock_retail_data.py`; `~/Applications/Muse Retail Demo.app` todavía lo invoca.

**Impacto:** un evaluador que use el skill ve una demo rota; además se contradice la garantía “nunca matar procesos ajenos”.

**Corrección propuesta**
- Reescribir el mock para emitir el contrato v2 completo (o retirarlo y apuntar a `mosceye/run_demo.sh`).
- Actualizar `SKILL.md`/`README.md` a la UI y contrato actuales.
- Cambiar `dev_demo.sh` para reutilizar el servidor sano y no usar `pkill`, o eliminar el script y dejar un único punto de entrada.
- Añadir un test que valide que el mock produce todas las claves que Charm consume.

#### H2. Error local pegado en Charm tras recuperarse el servidor
**Evidencia:** `esp32/simulator/src/retail_view.c`
- `s_local_error` solo se limpia en `retail_view_check()` (línea 273).
- En `refresh()`, tras pintar el estado bueno, la línea 259 vuelve a imponer `s_local_error`.
- Si se agota el timeout de 15 s, “SIN RESPUESTA. REINTENTA.” persiste aunque llegue un dato válido, hasta el siguiente chequeo manual.

**Impacto:** la UI miente sobre el estado del sistema; el usuario cree que sigue caído.

**Corrección propuesta:** limpiar `s_local_error` cuando `connected && good` (o cuando `!s_checking` y llega un request exitoso), y aplicar el error local solo mientras `s_checking` sea verdadero.

#### H3. Sin watchdog de inferencia: `busy` puede quedar bloqueado para siempre
**Evidencia:** `mosceye/sam_service.py`
- `_run()` no tiene timeout; si `vision.detect()` o `segment()` se cuelga (driver, MPS, modelo), el `finally` nunca corre.
- `busy=True` permanente ⇒ todo `submit()` devuelve 409 y el servidor queda inservible hasta reiniciarlo.
- Charm solo tiene un timeout de UI de 15 s; no recupera el servidor.

**Impacto:** fallo total silencioso en producción. Es el peor modo de fallo posible para una demo en vivo.

**Corrección propuesta**
- Añadir un watchdog: si un request supera N segundos (p. ej. 30), marcar `phase='error'`, `error='Tiempo de inferencia agotado.'`, `busy=False`, `counts_ready=False` y publicar.
- Opcional: `concurrent.futures` con `future.result(timeout=...)`, o un hilo monitor que observe `request_id` y `started_at`.
- Test que simule un `vision.detect` que duerme y verifique que `busy` vuelve a `False`.

#### H4. El último resultado se pierde al reiniciar y se publica un estado nulo
**Evidencia:** `Engine.__init__` crea el estado con todo en `None`; `start()` llama a `_publish()` antes de tener resultados. `CAJA_PATH` se sobrescribe con conteos nulos aunque hubiera un resultado válido de la sesión anterior.

**Impacto:** al reiniciar el servicio, Charm/Desktop pasan de un dato bueno a “sin datos”, y se destruye la evidencia del último chequeo.

**Corrección propuesta**
- Al arrancar, leer `CAJA_PATH`/`STATE_PATH` y conservarlo como **dato anterior** (`stale=True`, `published_epoch` del archivo), sin republicar nulos hasta el primer chequeo real.
- O no publicar `CAJA_PATH` hasta que `ready && phase!='idle'`.
- Añadir `stale` al contrato para que la UI lo muestre explícitamente.

---

### MEDIO

#### M1. `empty_minutes` está hardcodeado en 0
**Evidencia:** `sam_service.py` línea 87: `payload.update(empty_minutes=0, ...)`. El contrato y el skill lo presentan como un dato significativo; el mock lo calcula.

**Impacto:** dato falso presentado como real. Rompe la honestidad del resto del diseño.

**Corrección propuesta:** calcularlo en servidor (tiempo desde el último conteo con cola > 0, o desde el último cliente visto) y publicarlo; si no se puede calcular, omitirlo o publicar `null`, nunca `0`. Actualizar docs/UI.

#### M2. `store_calibrated=True` siempre
**Evidencia:** `vision.py` `classify_people()` devuelve `store_calibrated=True` incondicionalmente; solo significa “existe total”, no “calibrado”.

**Impacto:** nombre engañoso; un consumidor puede creer que la tienda está calibrada.

**Corrección propuesta:** derivarlo de la confirmación real de zonas o renombrarlo (`store_total_available`) y ajustar el contrato y la UI.

#### M3. `Engine.configure()` deja campos derivados obsoletos
**Evidencia:** `configure()` limpia muchos campos, pero no `masks_pending`, `warning`, `total_ms`, `people`, `frame_w`, `frame_h`, `detector`, `model`, `device`.

**Impacto:** tras cambiar configuración, `/api/mosceye` puede mostrar tiempos o dimensiones del frame anterior; confunde a Desktop y a tests.

**Corrección propuesta:** centralizar un `_reset_derived_state()` que limpie **todos** los campos por request y usarlo en `configure()`, `submit()` y el arranque.

#### M4. `preview.jpg` anota dentro del lock del motor
**Evidencia:** `preview()` mantiene `engine.lock` mientras ejecuta `annotate()` (CPU) sobre frame + detecciones + máscaras.

**Impacto:** bloquea `submit()`, `snapshot()` y la publicación mientras se genera el preview; en un momento de demo puede provocar 409 o latencia visible.

**Corrección propuesta:** copiar referencias inmutables bajo lock y ejecutar `annotate()` + `imencode()` fuera del lock (igual que ya se hace con el worker).

#### M5. `run_demo.sh` ignora `MOSCEYE_PORT`/`MOSCEYE_HOST`
**Evidencia:** `run_demo.sh` fija `http://127.0.0.1:8000` en health, espera y `open`; el servidor sí lee las variables.

**Impacto:** si el usuario cambia el puerto, el launcher comprueba/abre el puerto equivocado y puede arrancar un segundo servidor o fallar.

**Corrección propuesta:** `HOST=${MOSCEYE_HOST:-127.0.0.1}`, `PORT=${MOSCEYE_PORT:-8000}`, construir `BASE_URL` una vez y usarlo en todo el script. Añadir aviso si `HOST` no es loopback.

#### M6. Selección frágil del video de demo
**Evidencia:** `sam_service.py` línea 17: `VIDEO=next((HERE.parent/'camara footage para test').glob('*.mp4'),None)`.

**Impacto:** al añadir un segundo `.mp4`, el “video principal” puede cambiar sin aviso; el README dice que el segundo se conserva fuera del flujo, pero el código no lo garantiza.

**Corrección propuesta:** nombre canónico (`principal.mp4`) o variable `MOSCEYE_VIDEO`; si hay varios, elegir explícitamente y documentarlo.

#### M7. SAM activado por defecto en CPU
**Evidencia:** `Vision.load()` mantiene `sam_enabled=True` aunque `device='cpu'`.

**Impacto:** en una Mac sin MPS, SAM ViT-B puede tardar decenas de segundos y disparar el timeout de UI; la demo parece colgada.

**Corrección propuesta:** en CPU, desactivar SAM por defecto y publicar un `warning` claro; permitir activarlo manualmente desde Configuración.

#### M8. Sin métricas contra verdad humana
**Evidencia:** el README lo reconoce; hay 12 frames en `audit/evidence/core-v2/` listos para etiquetar, pero no hay MAE/precisión/recall.

**Impacto:** no se puede afirmar calidad ni comparar cambios de modelo; las mejoras son a ciegas.

**Corrección propuesta:** etiquetar a mano los 12 frames (fila, caja, visibles), guardar `labels.json` y un script `audit/evaluate.py` que calcule MAE y matriz de confusión. Es el mayor multiplicador de calidad a medio plazo.

#### M9. Privacidad y exceso de certeza en etiquetas
**Evidencia**
- `audit/evidence/core-v2/*-raw.jpg` contiene rostros identificables de CCTV.
- `retail_view.c` línea 141: “CAJERO PRESENTE” / “SIN CAJERO”; “PERSONAS EN TIENDA” (línea 435).
- La clasificación es posicional (centro inferior dentro de un polígono), no identidad ni uniforme.

**Impacto:** riesgo de privacidad al compartir evidencia; la UI afirma más de lo que el modelo sabe.

**Corrección propuesta:** difuminar rostros en la evidencia que se distribuya (o no versionarla), añadir nota de privacidad, y suavizar etiquetas: “CAJA ATENDIDA” / “CAJA SIN ATENDER”, “PERSONAS VISIBLES”. Mantener la incertidumbre explícita.

---

### BAJO

#### B1. Faltan cabeceras de licencia y procedencia
`retail_view.c`, `retail_voice.c`, `retail_voice_mac.m`, `retail_number_font.c`, `mosceye_logo.c` no tienen cabecera Apache/OFL. La fuente deriva de Montserrat Bold (OFL) y no indica cómo regenerarla.
**Fix:** cabeceras SPDX, nota de origen de la fuente, comando de regeneración y licencia del logo.

#### B2. `requirements.txt` es un `pip freeze`
No hay instrucciones reproducibles para una Mac limpia, ni URL/checksum del checkpoint SAM.
**Fix:** requirements curado (o `pyproject.toml`), `scripts/bootstrap.sh`, URL + `sha256` del checkpoint en el README.

#### B3. Falta `.gitignore`
`.venv` (944 MB), `checkpoints` (358 MB), footage (74 MB), evidencia (31 MB), `__pycache__`, `build`, `backups`.
**Fix:** crear `.gitignore` antes del primer commit (ver C1).

#### B4. Servidor sin autenticación si se expone
Por defecto escucha en `127.0.0.1`, pero `MOSCEYE_HOST` permite `0.0.0.0` sin auth y la API expone cámara, captura, configuración y reproducción.
**Fix:** rechazar bind no-loopback sin token explícito, o documentar el riesgo en mayúsculas.

#### B5. Deriva documental
`README.md` declara `IMPLEMENTACION_CORE_V2` como estado vigente, pero ese documento dice “Sin bienvenida obligatoria”, ya falso; los cambios de Charm/voz están en `INFORME_CHARM` y `UX_CHARM`.
**Fix:** un único `STATUS.md`/`CHANGELOG.md` actualizado, y marcar los informes antiguos como históricos.

#### B6. El watcher de señales se traga errores
`_watch_signals()` captura `OSError`/`JSONDecodeError` sin log. Un trigger corrupto o un fallo de permisos pasa desapercibido.
**Fix:** loguear a un archivo de diagnóstico y publicar `warning` cuando falle la lectura del trigger.

---

## 3. Lo que está bien (no tocar)

- Arquitectura de un solo request y un solo productor de frames; IDs y ack en vez de mtime.
- Detección semántica primero; SAM solo refina y **nunca** cambia conteos.
- Publicación atómica y contrato con heartbeat.
- Distinción explícita entre “desconocido” y “cero”.
- Tests de audio con driver dummy; no tocan micrófono, portapapeles ni WhatsApp.
- Documentación honesta de límites (niños, oclusiones, duplicados, simulación).
- `run_demo.sh` principal ya reutiliza servidor sano y no mata procesos ajenos.
- Métricas medidas y reproducibles (0,467 s conteo; 1,591 s con SAM).

---

## 4. Plan de acción recomendado

| Orden | Acción | Esfuerzo | Riesgo si no se hace |
|---|---|---|---|
| 1 | `git init` + `.gitignore` + commit inicial + tag | Bajo | Pérdida total del proyecto |
| 2 | Arreglar `s_local_error` en `retail_view.c` | Muy bajo | UI miente tras recuperarse |
| 3 | Watchdog de inferencia en `sam_service.py` | Bajo | Servidor bloqueado en vivo |
| 4 | Restaurar último resultado al reiniciar | Bajo | Pérdida de dato/evidencia |
| 5 | Actualizar o retirar mock/skill y `dev_demo.sh` | Medio | Demo de evaluador rota |
| 6 | `empty_minutes` real o `null`; `store_calibrated` honesto | Bajo | Datos falsos |
| 7 | Reset de estado en `configure()`; preview fuera del lock | Bajo | Datos obsoletos / latencia |
| 8 | `run_demo.sh` con `MOSCEYE_PORT/HOST`; video canónico | Bajo | Launcher incoherente |
| 9 | Etiquetar 12 frames y calcular MAE/precisión | Medio | Mejoras a ciegas |
| 10 | Privacidad: difuminar evidencia, suavizar etiquetas | Bajo | Riesgo ético/legal |
| 11 | Licencias, bootstrap, docs consolidados | Bajo | Ambigüedad de uso |

**Sugerencia:** hacer 1–4 en una sola sesión (son pequeños y eliminan los riesgos reales), y dejar 5–11 como siguiente bloque.

---

## 5. Nota metodológica

- Revisión de solo lectura: no se creó ni modificó ningún archivo del proyecto.
- Comandos ejecutados para verificar estado: `unittest discover`, `ctest`, `git status`, `git rev-parse`, `du -sh`.
- Los tamaños citados son de esta máquina y pueden variar.
