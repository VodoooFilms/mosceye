# MOSCEYE — Auditoría: ¿el reporte de SAM es un solo frame?

| Campo | Valor |
|---|---|
| **Fecha** | 2026-10-26 (America/Guayaquil) |
| **Pregunta auditada** | ¿La mejor integración de SAM en MOSCEYE es sobre un instante / un solo frame, y por eso el flujo actual es caótico? |
| **Informe leído** | `mosceye/STATUS_2026-10-26_15-20.md` (último, 15:20) + `mosceye/AUDIT_2026-10-26_13-27.md` |
| **Código auditado** | `mosceye/sam_service.py`, `mosceye/desktop/index.html`, `muse-gadget-sdk/esp32/simulator/src/retail_view.c` |
| **Veredicto** | ✅ **SÍ. La hipótesis es correcta.** SAM hoy es una foto, no un video. El caos no es un bug suelto: es el roce entre una UX que simula video en vivo y un modelo que entrega una foto 12–14 s después. |

---

## 1. Qué dice el último reporte (15:20) — y qué confirma

El STATUS §3 ya lo admite sin nombrarlo así:

- SAM `vit_b` + `SamAutomaticMaskGenerator` (`points_per_side=32`) sobre MPS.
- *"Modo ráfaga: cada CHEQUEAR analiza **3 frames** a 1 s de distancia y gana el frame mediano."*
- Duración del ciclo: **~42 s (3 frames × ~12–14 s)**.
- §6: el modo "en vivo" continuo da **~0.17 fps** y *"no es oficial"*.
- §9 #2: latencia ~42 s = deuda media; mitigaciones = 1 frame (~12 s) o MobileSAM.

Es decir: el propio reporte describe un sistema de **fotografías seriadas**, presentado al usuario como si fuera una cámara que "mira".

## 2. Qué hace el código, frame a frame

### 2.1 La unidad real de trabajo es UNA imagen quieta

`mosceye/sam_service.py:187-188`:

```python
def analyze_frame(frame, gen=None):
    """Run SAM on ONE still frame; return its count + mask detail."""
```

- Se usa `SamAutomaticMaskGenerator` (SAM 1, modelo de **imagen**) en `load_sam()` (líneas 102–119). No hay `Sam2VideoPredictor`, no hay memoria temporal, no hay propagación de máscaras entre frames.
- El comentario del propio archivo (líneas 22–25) lo dice: *"SAM is still an image model: there is no tracking between frames, just voting."*
- `dedup()` deduplica máscaras **dentro** de ese frame. Nada cruza de un frame al siguiente…

### 2.2 …salvo dos parches post-hoc, que no son tracking

1. **Voto mediano** (`run_check`, línea 319): ordena los 3 resultados por `people_in_queue` y se queda con el del medio. Los otros dos frames se descartan como evidencia: solo sobreviven como números en `burst_queues` / `burst_results`.
2. **Anti-cartel** (`filter_static_furniture`, línea 218): si una bbox es pixel-idéntica (IoU ≥ 0.97) en *todos* los frames, se declara mobiliario. Es la única "memoria" entre frames, y es una regla de descarte, no seguimiento de personas.

### 2.3 El reporte final ES un solo frame (el mediano)

Líneas 319–341 de `run_check()`: todo lo que MOSCEYE publica sale de `median_r`:

| Salida | Origen |
|---|---|
| `people`, `people_in_queue`, `cashier_present` | `median_r` (1 frame) |
| `masks_total`, `masks_detail[]`, `frame_w/h` | `median_r` (1 frame) |
| `/tmp/mosceye_annotated.jpg` (`preview.jpg`) | `annotate(median_r["frame"], median_r)` |
| `frame_time_sec` / timestamp | el instante de ese frame |
| `/tmp/caja_status.json` → Charm | `{people_in_queue, cashier_present, empty_minutes}` derivados de ese frame |

El Charm, además, reduce eso a 3 escalares que lee por polling cada 500 ms (`retail_view.c:33-34`). **El contrato completo SAM→MOSCEYE es: "en este instante, en esta foto, estimé N personas en el ROI". Nada más existe.**

## 3. Por qué el flujo se siente caótico (causa raíz)

No es un problema de pulido visual. Es un **desajuste de paradigma** entre 3 capas:

| Capa | Qué promete | Qué es en realidad |
|---|---|---|
| Desktop "cámara" | Video fluido ~11 fps (`camera.mjpg`) | Reproducción del footage; SAM **no** analiza ese stream |
| Desktop "SAM en grande" | "SAM está mirando ahora" | Snapshots `burst/N.jpg` que aparecen cada ~12–14 s, de frames capturados 1 s aparte pero mostrados como secuencia |
| Charm | `ANALIZANDO SAM...` → número | Espera ~42 s un número que resume **un** frame de hace hasta ~40 s |

Consecuencias medibles (todas ya registradas en el STATUS):

1. **Latencia estructural**: 42 s no se arregla con UI; es 3 × inferencia de imagen. Cada frame extra multiplica la espera para ganar un voto.
2. **Falsa continuidad**: el usuario ve gente moviéndose en el MJPEG mientras el conteo corresponde a una foto vieja y quieta. Cuando el número no coincide con lo que ve *ahora*, el sistema parece "roto" aunque haya funcionado.
3. **Modo vivo fantasma**: `live_worker` (línea 366) es un segundo camino (pps20, ~0.17 fps) que compite por el mismo `_sam_lock` (línea 72) con el chequeo oficial. Dos verdades distintas sobre la misma escena = confusión garantizada. El STATUS ya lo dejó detenido "para que no compita".
4. **El instante se pierde**: el resultado no dice "esto era la fila a las 15:19:33 en el frame @Xs" en la experiencia principal; se presenta como estado presente. La única defensa actual es el `LAST CHECK` en gris del Charm — que en realidad es la pista de cuál es el modelo correcto (ver §4).

## 4. La mejor integración: diseñar MOSCEYE como una FOTO, no como un video

### Principio

> **CHEQUEAR = sacar una foto. SAM = revelar la foto. Resultado = lo que había en ese instante, con su hora.**

Eso no es recortar ambición: es alinear producto, modelo y contrato. SAM 1 es de los mejores "ojos de un instante" que existen; es un mal motor de video.

### Flujo recomendado (ciclo de presentación)

1. Charm: `CHEQUEAR` → Desktop despierta.
2. Desktop **congela el frame exacto** que se va a analizar (nada de MJPEG fluido durante el conteo; el video puede correr *antes* de disparar, como visor).
3. Sobre **esa misma foto quieta**: línea de escaneo / "SAM contando…" (~12 s con vit_b pps32, ~2 s si se prueba MobileSAM).
4. Las máscaras aparecen **sobre esa misma foto**. El número del Charm y la foto anotada son la misma evidencia, del mismo instante.
5. Resultado con sello: `15:19:33 · frame @15s · 5 en fila`. Al volver, queda como `LAST CHECK` en gris — que ya existe y hoy es lo más honesto de la UX.

Cambios concretos que esto implica:

| # | Cambio | Efecto |
|---|---|---|
| 1 | Ráfaga por defecto: **3 → 1 frame** (`burst_frames`, ya configurable sin tocar código) | Ciclo 42 s → ~12 s. Demo 3× más ágil |
| 2 | Si se extraña robustez: ráfaga **silenciosa** (SAM vota entre 3, la UI muestra 1 foto + "verificado en 3 fotos: 5·5·3") | Se conserva el anti-cartel (exige ≥2 frames, línea 220–222) sin fingir video |
| 3 | Desktop durante el conteo: imagen **congelada** del frame bajo análisis, no `camera.mjpg` | Desaparece la falsa continuidad; lo que ves = lo que SAM contó |
| 4 | `live_worker` / pestaña "SAM en vivo": eliminar del pitch o rotular `EXPERIMENTAL · 0.17 fps` | Un solo camino oficial = una sola verdad |
| 5 | Mostrar siempre el timestamp del **frame**, no el de llegada del resultado | El usuario entiende "foto de hace X" en vez de "error de conteo" |

### Qué NO hacer (por ahora)

- **No** perseguir "SAM en video" con SAM 1 a fuerza de loops: 0.17–0.2 fps nunca parecerá vivo, y cada intento reintroduce el caos auditado.
- Si post-hackathon se quiere video real, el camino es otro modelo: **SAM 2 video** (memoria + propagación) o detector+tracker (p. ej. YOLO + ByteTrack) con SAM solo para segmentar. Es un cambio de motor, no un ajuste de esta integración.

## 5. Estado al momento de auditar (nota operativa)

Al correr esta auditoría, el sistema **no estaba levantado**: sin proceso `sam_service.py`, sin `/tmp/caja_status.json` ni `/tmp/mosceye_status.json`. Nada que invalide lo anterior (el STATUS 15:20 dejó el ciclo verificado a las 15:19:33), pero para retomar: `./mosceye/run_demo.sh` y verificar **una sola** instancia con `pgrep -fl sam_service.py` (deuda #5 del STATUS).

## 6. Conclusión en una frase

**Sí: el reporte de SAM es — y siempre fue — un solo frame (el mediano de 3 fotos independientes). La integración correcta no es disfrazarlo de video, sino abrazar el instante: una foto, un conteo, una hora. El flujo se ordena solo cuando la UX deja de prometer movimiento que el modelo no tiene.**

---
*Auditoría generada el 2026-10-26 tras leer `STATUS_2026-10-26_15-20.md` y revisar `sam_service.py` línea a línea. No se modificó código: el cambio de ráfaga 3→1 ya es configurable desde MOSCEYE Desktop (`burst_frames`).*
