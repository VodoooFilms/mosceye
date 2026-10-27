# MOSCEYE

Un chequeo desde Charm o Desktop captura un instante de la cámara y devuelve personas en fila y personas visibles. Todo se procesa localmente en esta Mac.

## Instalación en una Mac limpia

```sh
./mosceye/scripts/bootstrap.sh          # venv + dependencias + simulador
./mosceye/scripts/bootstrap.sh --sam    # además descarga SAM (358 MB, SHA-256 verificado)
```

Requiere Python 3.11+, CMake y Ninja. El lockfile reproducible es
`requirements.txt`; las dependencias directas están en `requirements.in`.
Sin el checkpoint SAM el conteo sigue funcionando y los contornos quedan
desactivados con una advertencia. En macOS sin GPU (MPS), SAM también queda
desactivado por defecto para evitar latencias de decenas de segundos; se puede
forzar con `MOSCEYE_SAM_ON_CPU=1`.

## Video de prueba

El footage de demo **no se incluye en este repositorio**: es material CCTV de
terceros con rostros identificables. MOSCEYE funciona con cualquier fuente:

```sh
# Un archivo local tuyo
MOSCEYE_VIDEO=/ruta/a/tu-video.mp4 ./mosceye/run_demo.sh

# Una URL directa de stream (MP4/HLS)
MOSCEYE_VIDEO=https://ejemplo.com/tienda.m3u8 ./mosceye/run_demo.sh

# YouTube, resolviendo antes la URL directa (experimental: caduca y
# requiere red; úsalo solo con videos que tengas derecho a usar)
MOSCEYE_VIDEO=$(yt-dlp -g "https://www.youtube.com/watch?v=...") ./mosceye/run_demo.sh
```

Sin `MOSCEYE_VIDEO`, se usa `principal.mp4` dentro de la carpeta local
`camara footage para test`, junto al workspace. Al cambiar de video hay que
recalibrar las zonas de fila y caja desde Desktop → Configuración.

## Versión y respaldo

El código de `mosceye/` está versionado en su propio repositorio git; la
integración del simulador vive en el repositorio existente de
`muse-gadget-sdk`. No hay un repositorio en la raíz del workspace. Esto evita
que un `git clean` en el SDK borre la UI, la voz o el skill. Ver `VERSIONING.md`.

La parte Charm (UI 412×412, voz e integración con el simulador) está copiada
en [`simulador/`](simulador/README.md), con instrucciones para montarla sobre
una copia del SDK. Es código de simulador de escritorio, no firmware.

## Ejecutar

Desde la raíz del workspace:

```sh
./mosceye/run_demo.sh
```

Abre el Desktop en http://127.0.0.1:8000/desktop y el simulador Charm 412×412. En Charm: **EMPEZAR** abre las dos pantallas de fila y tienda, navegables con drag o puntos de página; **Inicio** vuelve a la bienvenida. Pulsa **Chequear** en cualquiera de las apps. EMPEZAR también reinicia la demo: el servidor vuelve a reproducir el video desde el principio y descarta el análisis anterior (conteos, cajas y contornos SAM) en todas las pantallas, para empezar cada demo desde cero. Si hay un chequeo en curso, EMPEZAR no lo interrumpe. La bienvenida no detiene el servicio. El video principal es el único fixture de la demo; el segundo archivo se conserva fuera del flujo.

El launcher reutiliza un servidor v2 sano y no mata procesos ajenos. Si inicia su propio servidor, lo cierra cuando termina el simulador. Requiere el entorno `.venv`, CMake y el build del SDK ya configurado en esta máquina.

## Mensaje de voz al cajero

En cualquiera de las dos pantallas internas, toca la **C**. Mantén pulsado **MANTÉN PARA GRABAR** y suelta para terminar (entre medio segundo y 30 segundos). La primera vez macOS solicita acceso al micrófono; después de autorizarlo, vuelve a mantener pulsado. Puedes **ESCUCHAR**, **DETENER** la escucha o **REPETIR** la grabación. **Volver** descarta el borrador y conserva la pantalla y el conteo.

Con WhatsApp normal, **ABRIR WHATSAPP** convierte el audio a M4A/AAC, copia el archivo al portapapeles y abre WhatsApp instalado o WhatsApp Web. Elige el chat, pega con **⌘V** y envía desde WhatsApp. Esta acción no envía automáticamente ni confirma recepción. No necesita token de WhatsApp Business. El audio se comparte como archivo de audio; no se afirma que sea una nota de voz nativa grabada en WhatsApp.

La captura y reproducción usan SDL Audio; la conversión y el portapapeles usan macOS. Los WAV de borrador se eliminan al volver, repetir o cerrar. La copia M4A compartida permanece en una carpeta temporal privada para que se pueda pegar después de cerrar Charm. En Linux se puede grabar y escuchar; la acción de compartir indica que requiere macOS.

Pruebas: `./mosceye/.venv/bin/python -m unittest discover -s mosceye/tests -p 'test_charm_*.py'`. Las pruebas de audio usan el driver dummy de SDL y no acceden al micrófono, portapapeles ni WhatsApp. Capturas de los estados: `audit/evidence/charm-voice/`.

## Cómo funciona ahora

1. Un único productor entrega frames con IDs. El navegador pide un frame conocido y lo envía al chequear; el Charm toma el último frame disponible.
2. El servidor reserva un request bajo lock y fija frame y configuración antes de iniciar el worker.
3. **Faster R-CNN ResNet-50 FPN v2**, de TorchVision, detecta la clase persona. Una sola lista determina total visible, fila y personal de caja. La pertenencia a zonas usa el centro inferior de la caja.
4. Los números se publican inmediatamente. **SAM ViT-B de Meta** calcula un embedding de esa imagen y recibe las cajas como prompts por lotes; añade contornos sin modificar el conteo.
5. Desktop mantiene la captura como evidencia hasta que se vuelva a Cámara. Charm muestra ambos datos, el instante y la antigüedad. Errores y zonas sin configurar se muestran como desconocidos, nunca como cero.

Primera ejecución: TorchVision descarga pesos oficiales a su cache de PyTorch. SAM usa `checkpoints/sam_vit_b_01ec64.pth`. En las siguientes ejecuciones no se necesita red para inferir. Si SAM no está disponible, el detector sigue devolviendo conteos y cajas con una advertencia.

Fuentes: [detector TorchVision](https://github.com/pytorch/vision/blob/main/torchvision/models/detection/faster_rcnn.py), [SAM de Meta](https://github.com/facebookresearch/segment-anything).

## Resultados medidos en esta M4

Versión final, detector a 960 px de lado corto con límite 1700 px, 12 instantes del video principal:

| Tiempo en servidor | Mediana | p95 de estas 12 muestras |
|---|---:|---:|
| Conteo disponible | 0,467 s | 0,489 s |
| Conteo + contornos SAM | 1,591 s | 2,217 s |

El polling del navegador y del simulador añade hasta aproximadamente 350/250 ms, respectivamente, más carga de imagen. Estas métricas no son una medición de latencia hasta pantalla. El primer request de la muestra terminó en 1,999 s; una muestra de contornos llegó a 2,483 s. Los pesos se precalientan al iniciar.

También se verificaron 20 requests consecutivos y una ráfaga de 8: uno aceptado y siete respuestas 409, sin quedar bloqueado. La evidencia está en `audit/evidence/core-v2/validation.json`.

## Configuración

Desktop → **Configuración**:

- Fuente: video principal o cámara de esta computadora.
- Score mínimo del detector y contornos SAM opcionales.
- Editor de polígonos de fila y personal, con 3–12 puntos por zona.
- Confirmación de zonas. Cambiar de fuente invalida la calibración; primero guardar la fuente, luego ajustar sus zonas sobre su propia imagen.

La configuración se guarda en `camera_config.json`. El perfil incluido es una aproximación para el video de demo. No demuestra que toda persona dentro de la zona esté esperando ni que toda persona en caja sea empleada.

## API y contrato

| Ruta | Uso |
|---|---|
| `GET /health` | Disponibilidad del motor y versión de contrato |
| `GET /api/mosceye/frame` | Metadata y URL del frame más reciente |
| `GET /api/mosceye/frame.jpg?id=...` | Frame conocido mientras exista en el buffer |
| `POST /api/mosceye/check` | 202 con `request_id`; body opcional `{frame_id, client_request_id}` |
| `GET /api/mosceye` | Fase, números, detecciones, contornos, tiempos y error |
| `GET /api/mosceye/capture.jpg?request_id=...` | Imagen limpia fijada para el request actual |
| `GET /api/mosceye/preview.jpg` | Evidencia exportable con cajas y contornos |
| `GET/POST /api/mosceye/config` | Leer/guardar configuración; 409 si hay trabajo activo |
| `POST /api/mosceye/play` / `stop` | Controles del fixture; play admite `{seek_sec}` para pruebas |

`checking` termina cuando están listos los números; `busy` continúa mientras se completan los contornos. Un nuevo chequeo durante `busy` recibe 409. Un frame expirado también recibe 409 con motivo. Cada request limpia los datos anteriores antes de detectar.

`stale=true` significa que el resultado se restauró de la sesión anterior y no
se midió ahora; Desktop lo atenúa y Charm lo muestra como “DATO ANTERIOR”. El
servidor conserva el último resultado bueno hasta 24 h y no lo sobrescribe con
nulos al reiniciar. `empty_minutes` es `null` cuando no se puede calcular y
solo cuenta desde la última fila no vacía o la última caja desatendida; nunca
se publica un cero inventado. `store_calibrated` refleja la calibración de
zonas; el total visible sigue disponible en `people_in_store` y se anuncia con
`store_total_available`.

Puente local de simulador: señal atómica `/tmp/mosceye_trigger.json`, ack `/tmp/mosceye_trigger_ack.json`, resultado `/tmp/caja_status.json`. Todos comparten IDs; no se usa mtime para decidir que un resultado llegó. El contrato incluye fase, error, antigüedad y heartbeat. No correr el mock antiguo a la vez.

Variables opcionales:

| Variable | Default | Uso |
|---|---|---|
| `MOSCEYE_PORT` | `8000` | Puerto HTTP |
| `MOSCEYE_HOST` | `127.0.0.1` | Interfaz de escucha; fuera de loopback exige `MOSCEYE_TOKEN` |
| `MOSCEYE_TOKEN` | vacío | Bearer para clientes remotos; localhost queda exento |
| `MOSCEYE_RUNTIME_DIR` | `/tmp` | Carpeta de estado, ack y logs |
| `MOSCEYE_VIDEO` | video principal | Fixture alternativo |
| `MOSCEYE_INFERENCE_TIMEOUT` | `30` | Segundos antes de que el watchdog libere un request colgado |
| `MOSCEYE_SAM_ON_CPU` | `0` | `1` fuerza SAM en CPU |

El servicio sigue escuchando únicamente en localhost por defecto. Si se expone
en la red, el token es obligatorio; Desktop no envía el token, así que para uso
remoto hay que usar un proxy o un cliente propio.

## Verificar

```sh
mosceye/.venv/bin/python -m unittest discover -s mosceye/tests -v
cmake --build muse-gadget-sdk/esp32/simulator/build --parallel
ctest --test-dir muse-gadget-sdk/esp32/simulator/build --output-on-failure
# Con el servicio funcionando: modifica el instante del fixture y la opción SAM durante la prueba.
mosceye/.venv/bin/python mosceye/audit/validate_core_http.py --port 8000
```

Las capturas comparables de 12 instantes, JSON y prueba Charm→server están en `audit/evidence/core-v2/`. Los scripts de la auditoría anterior cargan el servicio respaldado, para poder reproducir sus defectos originales sin confundirlos con la implementación nueva.

## Evaluación contra etiquetas

```sh
./mosceye/.venv/bin/python mosceye/audit/evaluate.py
./mosceye/.venv/bin/python mosceye/audit/evaluate.py --check-labels
```

`audit/labels.json` guarda conteos humanos por frame. Un `null` significa “sin
etiquetar” y se excluye del promedio, no se cuenta como cero. El primer pase
solo etiqueta personas visibles y presencia de caja; la fila requiere revisar
las zonas sobre cada frame. Marca `reviewed: true` solo después de esa revisión.

## Privacidad de la evidencia

Las imágenes `*-raw.jpg` contienen rostros identificables de CCTV y están
excluidas de git por `.gitignore`. No las publiques sin redactar. Para generar
copias con los rostros pixelados:

```sh
./mosceye/.venv/bin/python mosceye/scripts/redact_evidence.py mosceye/audit/evidence
```

El script descarga YuNet una vez (227 KB, SHA-256 fijo) y escribe archivos
`*-redacted.jpg`; nunca modifica los originales. Es una heurística: revisa el
resultado antes de compartirlo.

## Límites actuales

- Hay omisiones con niños y personas muy ocluidas, y pueden aparecer duplicados. Las zonas también pueden clasificar a alguien de paso como parte de la fila. Hay un arnés de evaluación (`audit/evaluate.py` + `audit/labels.json`) con un primer pase visual de 12 instantes; **las etiquetas aún no están revisadas por una persona** y la fila sigue sin etiquetar. El MAE de personas visibles es 0 en esas 12 muestras, pero debe confirmarse con anotación independiente.
- “Personas visibles” incluye personal; no representa ocupación de toda la tienda fuera del campo de visión.
- La app Charm modificada es del **simulador**. Falta portar y verificar transporte/UI en un Charm físico; estos archivos `/tmp` no son un transporte para otra máquina.
- No se identifica gente ni se mantiene tracking de identidad. Los IDs de cajas valen dentro del chequeo.

El respaldo anterior a esta implementación está en `backups/pre-core-2026-10-26/`. Los informes anteriores describen versiones pasadas; el estado vigente es este README, `CHANGELOG.md` y `AUDIT_MEJORAS_2026-10-26.md`. `IMPLEMENTACION_CORE_V2_2026-10-26.md` queda como documento histórico: su frase “sin bienvenida obligatoria” ya no aplica.


## Charm y marca compartida

Charm vuelve a tener bienvenida y dos pantallas de métricas. La **C** del cajero va llena si hay presencia, en contorno si no hay y atenuada si el estado es desconocido. Ambas pantallas comparten request, hora, carga y error.

Desktop y Charm usan Montserrat, el mismo emblema y los tonos naranja `#c75a23`, blanco `#fffdf9` y carbón `#29251f`. El navegador sirve la fuente localmente, sin depender de Google Fonts. La licencia está en `assets/Montserrat-OFL.txt`.

En macOS hay un preview nativo adicional, `MOSCEYE Charm.app`. Para reconstruirlo:

```sh
./mosceye/build_charm_app.sh
```

Este preview usa el servidor ya iniciado; `run_demo.sh` sigue siendo el punto de entrada para arrancar todo. Las pruebas de navegación envían eventos SDL down/move/up en un mismo intervalo para cubrir gestos rápidos. Ver `UX_CHARM_2026-10-26.md`.
