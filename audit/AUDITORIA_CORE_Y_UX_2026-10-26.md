# MOSCEYE — auditoría del core, integración Charm y UX

Fecha: 26 de octubre de 2026. Alcance: código actual, API local activa, imágenes de ambos videos y Desktop en navegador. Se añadieron únicamente este informe, scripts de diagnóstico y evidencia. No se modificó el motor ni las interfaces. No se verificó un Charm físico.

## Dictamen

El prototipo ejecuta segmentación real de SAM, pero todavía no tiene un contador fiable de personas. La causa principal es usar segmentación genérica más reglas de geometría como sustituto de detección semántica. Existe además un fallo reproducible de concurrencia en el request HTTP, y el visor no comparte realmente el mismo reloj de reproducción con la captura.

Las cajas pueden mostrarse rápidamente si vienen de un detector de personas. Generar cientos de máscaras de todos los objetos para después adivinar cuáles son personas es trabajo costoso y ambiguo para este objetivo. SAM puede conservarse como una segunda etapa de segmentación de las personas detectadas.

## Evidencia y mediciones

El servicio activo respondió `/health` con `ready=true`, dispositivo `mps`. Su último resultado al comenzar la auditoría fue 5 en fila, 16 en tienda y 148 máscaras, en 14.230 ms. Es una lectura del estado existente, no un request disparado por esta auditoría. Copias: `evidence/runtime-before.json`, `last-capture.jpg` y `last-result.jpg`.

En `last-result.jpg`, P4 cubre el cartel £1.95 y P2 cubre una zona de estantería. Son falsos positivos visibles. Los informes anteriores que hablan de ±2 personas o de “calibrado” no aportan un conjunto etiquetado que permita sostener esas cifras.

Benchmark nuevo: mismo frame @8 s del video principal, SAM ViT-B, MPS, una ejecución por variante:

| Grilla | Camino | Tiempo | Máscaras | Fila estimada | Tienda estimada |
|---|---|---:|---:|---:|---:|
| 32×32 | generate oficial | 13,412 s | 158 | 4 | 13 |
| 32×32 | progressive_generate | 12,508 s | 158 | 4 | 13 |
| 20×20 | generate oficial | 5,645 s | 98 | 3 | 11 |
| 16×16 | generate oficial | 3,823 s | 67 | 5 | 11 |

No son medidas de precisión: falta verdad manual etiquetada. Tampoco son percentiles de latencia. El camino progresivo se midió con callback vacío; excluye dibujar/publicar cada lote y el polling de las apps. La diferencia entre los dos primeros tiempos no demuestra una ventaja de velocidad: hubo calentamiento y una sola muestra por variante. Ambos produjeron las mismas cajas de candidatos en este frame.

Conclusión respaldada: bajar la grilla reduce trabajo, pero cambia el conteo de manera no monotónica; no arregla reconocer carteles como personas.

Reproducciones sin tocar el servidor: `reproduce_findings.py` confirmó tres defectos y guardó `evidence/reproductions.json`.

## Hallazgos priorizados

### P1 — Un request del Desktop puede quedarse en checking indefinidamente

`sam_service.py:765–773`, frente a la guarda de `run_check:545–549`.

El endpoint inicia un thread y luego pone `checking=True`. Si el thread comienza después de esa asignación, `run_check` interpreta que ya hay otro chequeo y retorna sin capturar ni inferir. Nadie vuelve a ponerlo en false. El siguiente request también retorna el estado bloqueado.

Se reprodujo ejecutando el handler real extraído por AST, con un scheduler diferido válido y el `run_check` real, sin cargar modelos ni alterar el servicio activo. No depende de que SAM sea lento.

Corrección: un único punto de admisión bajo lock debe reservar el trabajo y asignar `request_id` antes de encolarlo. El worker reservado no vuelve a competir por la misma guarda. Finalización y errores liberan la reserva en `finally`. Respuesta 202 con ID; solicitudes concurrentes se rechazan explícitamente o se asocian al trabajo en curso.

### P1 — El contador no reconoce la clase persona

`sam_service.py:144–152`, `379–418`.

`person_like` solo aplica ancho, alto, área, proporción, relleno e IoU predicha de máscara. `W` y `H` no se usan: los límites son píxeles absolutos. La IoU predicha estima calidad geométrica de la máscara, no probabilidad de que sea una persona.

El mismo objeto a otra resolución puede desaparecer del conteo; se reprodujo con un cambio de escala 4×. El cartel y la estantería de la evidencia son aceptados con este criterio.

Corrección de fondo: detecciones semánticas `person` antes del conteo. Usar SAM con prompts de cajas para refinar contornos cuando aporten valor. Ajustar proporciones y ROIs puede mitigar casos concretos, pero no sustituye un clasificador.

### P1 — Tienda y fila se calculan con universos diferentes

`sam_service.py:379–418`, `583–584`.

Fila deduplica por solapamiento de máscara; tienda además fusiona cajas con IoU ≥0,20 o cobertura ≥0,35. Dos personas parcialmente ocluidas pueden fusionarse en tienda y seguir siendo dos en fila. Reproducción sintética: fila=2, tienda=1.

`store_calibrated=True` significa únicamente `source == footage`; no comprueba calibración ni precisión. Las cajas/IDs publicados son solo de candidatos del checkout: no existe evidencia equivalente para auditar las 16 personas de tienda.

Corrección: una única lista de personas detectadas con IDs locales al request. Total visible = cardinalidad de esa lista. Fila y cajeros = subconjuntos definidos por zonas y roles; nunca dos procesos de agrupación distintos. Definir si “tienda” incluye personal. No declarar calibrado por el nombre del archivo.

Una cámara solo permite contar personas visibles en su campo de visión. Para afirmar ocupación total de toda la tienda hace falta cobertura suficiente o conteo persistente de entradas/salidas, que actualmente no existe.

### P1 — El video mostrado puede estar atrasado respecto del frame contado

`desktop/index.html:227–240`; `sam_service.py:882–893`.

Desktop abre el stream con `play_base_sec`, pero el stream suma tiempo desde la conexión nueva, no desde el inicio de la sesión del servidor. Recargar o reconectar después de 30 s reproduce desde la base anterior mientras `capture_instant` toma el playhead actual. El reset de loop también usa su propio reloj.

Además, en `refresh`, la condición de reproducción se evalúa antes de finalizar el conteo: con `playing=true`, el primer refresh al terminar convierte `counting` a `playing` y salta el bloque que debía mostrar el resultado. Con pestañas manuales, `cycleState='manual'` evita parte del flujo automático. El mensaje “el frame que está en pantalla” no está garantizado.

Corrección: un solo productor de cámara/frame con `frame_id`, instante de captura y buffer compartido. El request fija un frame de ese productor. Si se exige literalmente el último frame visto por el usuario, el cliente debe enviar su `frame_id`; la latencia de red impide garantizarlo solo con relojes. El resultado permanece visible hasta una acción explícita de volver a cámara o nuevo chequeo.

### P1 — El Charm actual está implementado en el simulador

`muse-gadget-sdk/esp32/simulator/src/retail_view.c:595–612`, `simulator/src/main.c` y `simulator/CMakeLists.txt`.

La app retail depende de archivos `/tmp` en la misma Mac. El servicio escucha en `127.0.0.1`. En los directorios de firmware revisados no apareció integración retail equivalente. Por tanto, lo comprobado es una demo local de simulador, no una instalación validada en un Charm físico.

Si la entrega exige dispositivo real, este es un requisito pendiente del core: integrar el transporte soportado por el gadget/Muse, devolver el mismo contrato de resultados y verificar un request completo en hardware. Cambiar localhost por una IP no basta para portar la UI ni el puente.

### P2 — Configuración y zonas pueden invalidar resultados silenciosamente

Las zonas checkout/cajero son constantes del primer video; no hay editor ni perfil por cámara. Seleccionar el segundo video o una webcam conserva esas zonas. El conteo de tienda se desactiva para esas fuentes, pero fila/cajero siguen publicándose sin calibración equivalente.

`POST /config` permite cambiar fuente mientras se procesa un frame. Al terminar, `run_check` usa la configuración global nueva para etiquetar un resultado que pudo haberse capturado de la fuente vieja. Debe capturarse un snapshot inmutable de configuración junto al request o impedir cambios durante el trabajo.

El cajero se decide por centro de máscara dentro de otra caja y se resta exactamente uno: una persona cliente en esa zona puede ser restada; varios trabajadores no se representan. Para delimitar fila, usar polígonos y un punto de apoyo como el centro inferior de la persona, con reglas evaluadas frente a oclusión; no asumir que toda persona dentro de un rectángulo está esperando.

### P2 — El puente puede perder señales y ocultar errores al Charm

`trigger_watcher:713–738` ejecuta `run_check` de forma síncrona dentro del watcher. Durante la inferencia no lee `start`/`stop`/`check`. El archivo de señal conserva solo el último mensaje y se escribe sin rename atómico desde C.

Charm solo confirma éxito si cambia el mtime en segundos de `caja_status.json` (`retail_view.c:434`). Si hay error, ese contrato no recibe el error; Charm espera hasta 90 s y puede volver a datos antiguos. Optimizar a menos de un segundo vuelve también frágil detectar resultados con mtime de segundos.

Corrección: contrato con `request_id`, `phase`, `captured_at`, `completed_at`, `source_id`, `config_version`, `counts`, `error`; polling por ID o entrega por el transporte del dispositivo. Para demo local se pueden mantener archivos, pero con mensajes atómicos y un worker separado del lector.

`atomic_json` usa un `.tmp` fijo por destino y hay escritores en varios threads; lockear publicaciones o usar nombres temporales únicos para evitar interferencias.

### P2 — Las visualizaciones representan más mediciones de las que existen

`retail_view.c:530–533`: el historial agrega el mismo resultado una vez por segundo, sin nuevas inferencias. El pico usa hora de lectura, no necesariamente hora del frame. `empty_minutes` extrapola entre chequeos sin observación continua; no demuestra minutos realmente vacíos.

`annotate:508–531` incrusta todas las cajas y máscaras en el JPEG. Aunque el usuario desmarque “Todas las máscaras”, la capa canvas desaparece pero las cajas incrustadas quedan. Los toggles no controlan de verdad la evidencia completa.

Corrección: historial por resultados nuevos; retirar duración de vacío si no se observa continuamente. Mantener imagen limpia más una capa de overlays controlable. No llamar confianza de persona a la IoU de SAM.

## Arquitectura recomendada para el hackathon

1. Una fuente de video, un productor de frames, un perfil de zonas.
2. `CHEQUEAR` crea un request y fija un frame + configuración.
3. Un detector semántico de personas devuelve cajas y scores. Medir un candidato ligero en esta M4 antes de elegirlo: no hay un detector de personas ya integrado y validado en el proyecto.
4. Filtrar duplicados y asignar cada detección a zonas desde la misma lista. Publicar fila y personas visibles, con timestamp e ID del request.
5. Si las máscaras son parte de la demostración de Meta, SAM recibe esas cajas como prompts: calcular embedding una vez por imagen y procesar los prompts en lote. Mostrar cajas primero; máscaras después con fase explícita. No retrasar el número solo para colorear mobiliario.
6. Desktop muestra evidencia del request; Charm muestra el mismo resultado y su antigüedad. Error y sin datos nunca equivalen a cero personas.

SAM 1 permite segmentación con prompts y generación automática de máscaras: [repositorio oficial](https://github.com/facebookresearch/segment-anything). SAM 2 añade memoria y propagación de objetos en video; esas capacidades no convierten los candidatos geométricos actuales en detecciones semánticas de personas: [repositorio oficial](https://github.com/facebookresearch/sam2).

Si usar exclusivamente modelos Meta es obligatorio, evaluar SAM 3 con concepto `person`: soporta segmentación por conceptos, pero la ruta local documentada requiere GPU CUDA y acceso al checkpoint; no debe prometerse su velocidad o despliegue directo en esta M4 sin probarlo. [Fuente oficial](https://github.com/facebookresearch/sam3). Otra infraestructura implica medir también transporte y disponibilidad; no se desplegó ni subió footage durante esta auditoría.

SAM 2/tracking tiene sentido si después se exige seguimiento continuo. Para un request ocasional, comenzar con una imagen y detección semántica reduce complejidad. Un cartel quieto no deja de ser falso positivo por seguirlo; una persona quieta en fila tampoco debe descartarse por inmovilidad.

## Un solo video

Conservar el principal de 111,05 s como único fixture inicial: tiene personas, oclusiones y variación de fila, y es el que corresponde a las zonas actuales. No significa que esté calibrado correctamente. El candidato cenital dura 299 s y muestra en el frame @8 s dos puestos atendiendo; puede reservarse para generalización después, sin borrar el archivo.

Antes de cambiar motor, etiquetar manualmente al menos 12 frames distribuidos por el video principal: cajas de personas visibles, pertenencia a fila y personal, con reglas para oclusiones y bordes. Evaluar error absoluto de conteo, falsos positivos, omisiones y latencia total. No elegir el modelo por verse más vistoso ni por contar parecido en un único frame.

## UX/UI propuesta una vez estabilizado el core

Mantener naranja y blanco, con fondo naranja uniforme o variación muy sutil. Superficies blancas opacas y tipografía carbón en Desktop facilitan jerarquía y lectura; reservar naranja para marca, selección y acción principal. Evitar el conjunto actual de gradientes fuertes, transparencias, sombras, emojis y cientos de cajas superpuestas.

Desktop: una vista de cámara/evidencia dominante y dos métricas principales, **Fila** y **Personas visibles**. Una sola acción **Chequear**. Estados explícitos: sin datos, capturando, detectando, resultado y error. Timestamp del frame siempre visible. Configuración con fuente y zonas; métricas técnicas y todas las máscaras en un panel diagnóstico secundario. El Desktop actual ni siquiera muestra `people_in_store` como métrica principal: “personas en zona” es otro valor.

Charm 412×412: número de fila como foco, total visible en una línea secundaria para que ambos datos aparezcan sin descubrir un swipe. Una acción **Chequear**, estado de conexión y hora/antigüedad del resultado. Si se conservan dos páginas, ambas comparten request y estado de error. Reemplazar ambigüedad de iconos C/T por etiquetas legibles. Mantener funcionalidad antes de animaciones; el core no necesita una secuencia de bienvenida para funcionar.

El request debe funcionar aunque el usuario no abra Desktop o no pulse antes “Empezar”. La reproducción del fixture es una herramienta de demo; la cámara del edge necesita disponibilidad independiente de la pantalla del Charm.

## Orden de implementación y criterios de cierre

1. Resolver admisión HTTP, IDs de request, errores y snapshot de frame/configuración. Validar que 20 requests consecutivos terminen o fallen explícitamente; concurrencia no queda atascada.
2. Incorporar detección semántica y lista única de personas. Etiquetar y medir los 12 frames. Cajas auditables para todas las personas del total; coherencia entre subconjuntos.
3. Unificar productor de video y evidencia. Recargar Desktop o cambiar pestaña no modifica qué frame corresponde al request. Evitar modos paralelos que compiten por SAM durante la demo.
4. Medir detector solo y detector + SAM con prompts. Objetivo inicial propuesto: resultado útil en ≤2 s; es una meta, no capacidad verificada. Registrar p50/p95 con varias ejecuciones, calentamiento separado y tiempo de captura/render incluido.
5. Verificar transporte y UI en Charm físico si forma parte de la entrega. La prueba actual es de simulador.
6. Aplicar jerarquía naranja/blanco a ambas apps; probar lectura, errores y controles a tamaño real. Animaciones después.

La carpeta `mosceye` no está dentro de un repositorio Git en esta ubicación. El SDK sí, con varios archivos retail sin seguimiento. Conviene establecer respaldo/versionado explícito antes de implementar. No se creó commit ni se cambiaron los archivos existentes del usuario.

## Repetir las pruebas

Desde la raíz del workspace:

```sh
mosceye/.venv/bin/python mosceye/audit/reproduce_findings.py
mosceye/.venv/bin/python mosceye/audit/benchmark.py
```

El segundo comando carga el checkpoint local y consume MPS; correrlo cuando no haya una inferencia de la demo. No modifica configuración ni resultados del servidor activo. Las imágenes y JSON del informe quedan en `audit/evidence`, fuera de `/tmp`.
