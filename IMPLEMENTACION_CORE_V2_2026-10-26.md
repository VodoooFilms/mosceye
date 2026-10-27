# MOSCEYE — implementación core v2

> **Documento histórico.** Describe el estado del 26 de octubre antes de las
> mejoras de `AUDIT_MEJORAS_2026-10-26.md`. Para el estado vigente, ver
> `README.md` y `CHANGELOG.md`.

26 de octubre de 2026 · Mac M4 / MPS. Cambios implementados y validados localmente.

## Qué cambió

- `sam_service.py`: reserva atómica de requests, estados explícitos, snapshots de fuente/configuración, errores publicables y liberación del worker en finally. Fases y números son comunes para API y Charm. Un fallo de SAM no invalida el conteo ya disponible.
- `camera.py`: único productor de video/cámara, buffer con IDs y timestamps; preview y captura usan los mismos frames. Reconectar el navegador no crea otro reloj. Errores de fuente no sirven un frame viejo como imagen actual.
- `vision.py`: detector semántico TorchVision Faster R-CNN ResNet-50 FPN v2, NMS sobre detecciones de persona, roles disjuntos desde una sola lista. SAM ViT-B procesa las cajas como prompts por lotes; se retiró la grilla automática del flujo productivo.
- Desktop: interfaz naranja/blanco con métricas principales y captura persistente, overlays controlables, zonas editables, errores visibles y diagnóstico secundario. Se retiraron ráfagas y modo SAM continuo que competían con el request.
- Charm simulado: vista de 412×412 naranja y blanca, fila y total visibles juntos, hora y antigüedad, confirmación por ID y error/heartbeat. En esta versión no había bienvenida obligatoria; la versión actual sí la tiene (ver `UX_CHARM_2026-10-26.md`).
- `run_demo.sh`: reutiliza el servidor v2 y evita los pkill globales de antes.

## Validación realizada

- 13 tests de core: admisión concurrente, liberación después de error, frame fijado, configuración bloqueada, expiración, coherencia de subconjuntos, invariancia de zonas por resolución, desconocido si no hay zonas y fallo de SAM sin perder conteo.
- Build del simulador y `ctest`: pasan.
- 12 requests reales sobre segundos 5, 8, 15, 25, 35, 45, 55, 65, 75, 85, 95 y 105 del video principal; imágenes y datos guardados.
- 20 requests consecutivos con SAM desactivado para aislar admisión/detección: todos finalizan. Ráfaga de 8: 202×1 y 409×7; siguiente request sigue siendo posible.
- Señal emitida por el simulador compilado, procesada por el servidor y reflejada con el mismo ID en el contrato. Captura real del render de Charm guardada.
- Botón Chequear de Desktop probado desde navegador. Ocultar cajas y contornos deja la imagen limpia. Borrar una zona y guardar produce error sin modificar la configuración.

Mediana/p95 de servidor sobre la versión final: conteo **466,5/488,8 ms**; completo con contornos **1591/2216,8 ms**. Son 12 muestras, no una garantía de rendimiento. El navegador poll cada 350 ms; Charm cada 250 ms. Los tiempos no incluyen medir el último píxel presentado en pantalla.

## Elección del detector y límites

Se compararon SSDlite, Faster R-CNN MobileNet 320, MobileNet de mayor resolución y ResNet-50 FPN v2. Los más pequeños eran rápidos pero omitían demasiadas personas visibles en la prueba inicial. Se eligió ResNet a mayor resolución; el conteo sigue llegando antes de los contornos de SAM.

La semántica ya evita usar la forma de un cartel como criterio de persona. Eso no elimina todos los errores del detector: la revisión de capturas todavía muestra omisiones, especialmente con oclusiones, niños y bordes. No se publican porcentajes de precisión ni márgenes ±N porque no hay ground truth independiente etiquetado. La colección de 12 frames queda preparada para ese trabajo.

El perfil de zonas de demo se amplió hasta el suelo visible de la espera. Las zonas asignan posiciones, no prueban conducta ni empleo. Otro ángulo de cámara exige configuración propia.

No se instaló firmware ni se validó un Charm físico. La UI y el puente local comprobados son los del simulador. No se creó infraestructura cloud ni se subió footage a terceros.

## Dónde mirar

- `audit/evidence/core-v2/validation.json`: resultados HTTP y latencias.
- `audit/evidence/core-v2/*-raw.jpg` / `*-boxes.jpg`: evidencia comparable de cada instante.
- `audit/evidence/core-v2/contact-raw.jpg` / `contact-boxes.jpg`: revisión visual.
- `audit/evidence/core-v2/charm-roundtrip.json`: request real desde simulador.
- `audit/evidence/core-v2/ui/`: capturas de ambas interfaces.
- `backups/pre-core-2026-10-26/`: código anterior respaldado.
