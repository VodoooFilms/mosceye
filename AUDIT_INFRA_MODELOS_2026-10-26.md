# MOSCEYE — Auditoría de infraestructura + mejor integración entre modelos de Meta

| Campo | Valor |
|---|---|
| **Fecha** | 2026-10-26 (America/Guayaquil) |
| **Alcance** | Toda la infraestructura de MOSCEYE + familia Segment Anything de Meta (SAM 1, SAM 2/2.1, SAM 3/3.1) |
| **Flujo implementado hoy** | EMPEZAR (Charm) → video en play → CHEQUEAR → SAM escanea **ese** frame → devuelve la info |
| **Fuentes de modelos** | READMEs oficiales `facebookresearch/segment-anything`, `facebookresearch/sam2`, `facebookresearch/sam3` (consultados 2026-10-26) |

---

## 1. Infraestructura auditada (qué hay realmente)

| Pieza | Estado real | Riesgo / nota |
|---|---|---|
| Hardware | Mac mini **M4, 16 GB, MPS. Sin GPU CUDA/NVIDIA** | Es EL dato que decide el modelo (ver §3) |
| Servicio SAM | `mosceye/sam_service.py`, FastAPI+uvicorn :8000, venv propio (torch MPS, opencv, segment-anything 1.0) | OK; `analyze_frame()` es la costura limpia para cambiar de modelo |
| Checkpoint | `sam_vit_b_01ec64.pth` (358 MB, SAM 1 ViT-B) — único modelo en disco | Sin SAM 2/3 descargados ni instalados |
| Desktop | `mosceye/desktop/index.html` servido por el mismo server; poll cada 1,2 s a `GET /api/mosceye` | Ahora sigue el flujo play→scan→resultado (ver §2) |
| Charm | Simulador LVGL 412×412 (`retail_view.c`); lee `/tmp/caja_status.json` cada 500 ms | **Todo MOSCEYE en el SDK sigue sin commitear** (untracked/modificado) 🔴 |
| Puente Charm↔SAM | Archivo de señal `/tmp/mosceye_trigger.json` + contrato `/tmp/caja_status.json` | Simple y probado; es demo-only (misma máquina) |
| Footage | 1270×720, **13,09 fps**, 111 s | El MJPEG ahora es *time-accurate*: lo que se ve = reloj del server |
| Skill retail-tracker | `mock_retail_data.py` escribe el **mismo** `/tmp/caja_status.json` con datos falsos | ⚠️ Nunca correr el mock junto al servicio SAM: pisa resultados reales sin avisar |
| Modo "SAM en vivo" | Loop SAM 1 pps20, ~0,17 fps, compite por `_sam_lock` | Queda como experimento; fuera del flujo oficial |

## 2. Flujo implementado (el que pidió el usuario)

```
Charm EMPEZAR ──{"action":"start"}──► server: PLAY. El video corre en el
                                       Desktop (MJPEG time-accurate) y el
                                       server es el reloj maestro (playhead).
        …el usuario mira la fila moviéndose…
Charm CHEQUEAR ─{"action":"check"}──► server: captura EL frame del playhead
                                       en ese instante → /tmp/mosceye_capture.jpg
                                       (el Desktop lo muestra CONGELADO bajo
                                       la línea de escaneo) → SAM 1 lo segmenta
                                       → cuenta en el ROI → preview anotada
                                       sobre LA MISMA foto + caja_status.json
                                       → el Charm enciende el número.
Charm → bienvenida ─{"action":"stop"}► video se duerme; al volver a EMPEZAR
                                       reanuda donde quedó.
```

Verificado de punta a punta el 2026-10-26 (server en `screen -S mosceye`):

| Prueba | Resultado |
|---|---|
| EMPEZAR (simulador real) | `PLAY desde @49.7s`; playhead avanza en tiempo real (24.47 → 27.52 en 3 s) |
| CHEQUEAR (señal manual) | captura @27.66s (= playhead de ese instante), SAM 13,6 s → 4 personas, **3 en fila**, cajero sí |
| CHEQUEAR (simulador real, escenario `start+check`) | captura @56.06s → 5 personas, **4 en fila**; `caja_status.json` actualizado |
| STOP | playhead se congela en 49.7s y el próximo PLAY reanuda ahí |
| `ctest` simulador | 1/1 passed |

Ya no hay ráfaga ni voto mediano en el camino oficial (`burst_*` queda solo
como compatibilidad en la API, siempre con 1 frame). El filtro anti-cartel,
que exigía ≥2 frames, queda fuera de este flujo: su trabajo pasa a ser
responsabilidad del modelo en la migración de §4.

## 3. Los modelos de Meta, comparados para MOSCEYE

| | **SAM 1** (hoy) | **SAM 2.1** | **SAM 3 / 3.1** |
|---|---|---|---|
| Qué es | Segmentación de **imagen** por prompts; `AutomaticMaskGenerator` segmenta *todo* sin saber qué es | Imagen **y video**: predictor de imagen + `SAM2VideoPredictor` con memoria streaming y masklets con identidad | Detector–tracker unificado: segmenta **todos los ejemplares de un concepto en texto** ("person") en imagen y video; 3.1 = Object Multiplex, tracking multi-objeto más rápido |
| ¿Sabe qué es una persona? | ❌ No: MOSCEYE lo adivina con heurística `person_like` (tamaño/proporción/IoU) → falsos positivos tipo cartel | ❌ Tampoco clasifica solo; pero sus boxes/máscaras del frame capturado pueden **sembrar el tracker** y confirmar identidad en el tiempo | ✅ **Sí**: prompt de texto `person` devuelve instancias con score. La heurística `person_like` desaparece |
| Video | No (fotos independientes) | ✅ Propagación con IDs persistentes | ✅ Sesión de video + prompts en un `frame_index` |
| Tamaño / velocidad oficial | ViT-B 358 MB; aquí ~12–14 s/frame en MPS | Hiera tiny 38,9M / small 46M params; 91/85 fps en A100 (CUDA) para video | 848M params |
| Requisitos oficiales | torch + MPS con parche float32 (ya resuelto aquí) | python ≥3.10, torch ≥2.5.1; kernel CUDA opcional | **python ≥3.12, torch ≥2.7, GPU CUDA 12.6+; checkpoint con acceso aprobado en Hugging Face** |
| ¿Corre en esta Mac M4? | ✅ Hoy, probado | ⚠️ Probable vía MPS (sin garantías: su documentación y ejemplos son CUDA-first) — exige benchmark antes de adoptar | ❌ **No** con la instalación oficial (CUDA obligatorio + checkpoint gated) |

*MobileSAM y similares: no son modelos de Meta (son destilaciones de terceros).
Acelerarían SAM 1 pero no resuelven su problema real —seguir sin clasificar—
así que no son "la mejor integración entre modelos de Meta".*

## 4. La mejor integración (recomendación por capas)

### Capa 1 — Hoy, hackathon, esta Mac: SAM 1 ViT-B, un frame ✅ IMPLEMENTADO
Es lo único probado de punta a punta en MPS. El flujo nuevo (§2) lo hace
honesto: una foto por chequeo, ~13 s, evidencia = la misma foto que ve el
usuario. **No migrar de modelo a horas de la presentación.**

### Capa 2 — Mejor integración Meta *en esta misma Mac*: SAM 2.1 Hiera (siguiente paso)
Detrás del interruptor que ya existe de facto (`analyze_frame()` es el único
lugar que toca el modelo), con dos roles que sí encajan con el flujo:

1. **Al CHEQUEAR**: `SAM2ImagePredictor`/AMG sobre el frame capturado —misma
   cuenta inicial, encoder Hiera mucho más liviano que ViT-B (38,9–46M vs
   ~91M params): debería bajar los ~13 s de espera.
2. **Confirmación temporal real** (reemplaza a la ráfaga y al anti-cartel):
   sembrar `SAM2VideoPredictor` con las boxes-persona del frame capturado y
   propagar ±2–3 s. Cuenta = **IDs de masklet presentes en el ROI en el
   instante capturado**; un cartel no se mueve ni se comporta como masklet
   seguido… y si persiste, su centroides inmóvil lo delata con datos de
   tracking, no con 3 fotos votando.

Gate obligatorio antes de adoptarlo: benchmark MPS en esta M4 (carga,
s/frame de imagen, propagación) contra los números SAM 1 de hoy. Si MPS lo
castiga, se queda SAM 1 y no se perdió nada: el contrato no cambia.

### Capa 3 — La mejor integración en absoluto: SAM 3 (edge con NVIDIA o nube)
Es el modelo que MOSCEYE siempre quiso: mapea 1:1 con el flujo del producto.

```
EMPEZAR   → video_predictor: start_session(video)
CHEQUEAR  → add_prompt(frame_index = frame actual, text="person")
          → instancias de persona con score en ese frame → contar en ROI
          → (opcional) el tracker sigue esos IDs mientras el video corre
```

Sin `person_like`, sin `dedup` artesanal, sin anti-cartel: el modelo entiende
el concepto. **Bloqueo hoy**: exige GPU CUDA 12.6+ y checkpoint con acceso
aprobado — es decir, otra máquina edge (o una instancia cloud), no esta M4.
Es la ruta de producción, no la del demo.

### Qué NO hacer
- No "SAM 1 en vivo" a fuerza de loops (0,17 fps: ya medido, ya caótico).
- No adoptar SAM 3 "a ver si MPS anda": la instalación oficial ni siquiera lo intenta sin CUDA.
- No mezclar el mock de la skill con el servicio real (mismo archivo de salida).

## 5. Deuda que esta auditoría deja anotada

| # | Severidad | Hallazgo |
|---|---|---|
| 1 | 🔴 Alta | Sigue sin commitear todo MOSCEYE en el SDK (`retail_view.c/.h`, fuentes, skill) — ahora incluye el nuevo `write_signal("start"/"stop")` |
| 2 | 🟠 Media | El anti-cartel quedó fuera del flujo de 1 frame: un objeto quieto con forma humana dentro del ROI volverá a contar. Mitigación barata sin SAM 2: comparar la captura contra la del chequeo anterior (si es el mismo "instante quieto", avisar). La solución de fondo es la Capa 2/3 |
| 3 | 🟠 Media | Puente `/tmp` + localhost: correcto para el demo, es lo primero a reemplazar por HTTP si SAM pasa a otra máquina (la API `/play`, `/check`, `/stop` ya existe) |
| 4 | 🟡 Baja | `MOSCEYE_BURST_*` y la pestaña "SAM en vivo" quedan como restos del paradigma anterior: conviene borrarlos tras la presentación para que el repo cuente una sola historia |

---
*Flujo implementado y verificado el 2026-10-26. Server corriendo en
`screen -S mosceye` (reanudar con `screen -r mosceye`). Para el demo completo:
`./mosceye/run_demo.sh`.*

---

## Addenda (2026-10-26, tarde): ver a SAM trabajando, sin línea de escaneo

La línea que barría la pantalla **se eliminó** (CSS + elemento): nadie la
pidió y no mostraba trabajo real. En su lugar, `progressive_generate()` en
`sam_service.py` abre el `SamAutomaticMaskGenerator` lote a lote (los mismos
16 lotes de su grilla 32×32, mismos umbrales, mismo NMS/postproceso final =
**mismas máscaras finales**) y publica `/api/mosceye/progress.jpg` tras cada
lote: el Desktop muestra las **cajitas apareciendo sobre el frame** mientras
SAM genera, con contador `N cajitas · grilla X/1024`. La publicación en vivo
es liviana (solo rectángulos) para no enlentecer: verificado — lote
320/1024 → 184 cajitas visibles; final 544 provisorias → **161 finales en
13,4 s**, 5 personas / 4 en fila (idéntico al camino cerrado anterior).
También se corrigió que al recargar el Desktop, el standby tapaba un
resultado ya terminado: ahora muestra directamente el frame contado.
