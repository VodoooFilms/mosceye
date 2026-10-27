# MOSCEYE Charm — parte del simulador

Esta carpeta contiene la interfaz Charm 412×412 de MOSCEYE tal como corre en
el simulador de escritorio de Muse Gadgets: bienvenida, dos pantallas de
métricas (fila y personas visibles), flujo de mensaje de voz y la integración
con el motor local.

> **Es código de simulador, no firmware.** No se compila para un Charm físico:
> se comunica con el servidor por archivos en `/tmp`, usa SDL para audio y
> AppKit/AVFoundation en macOS. Portar a hardware es trabajo futuro.

## Contenido

| Archivo | Qué es |
|---|---|
| `src/retail_view.c/.h` | UI LVGL: bienvenida, páginas de métricas, arrastre entre páginas, botón CHEQUEAR y lectura del contrato v2 |
| `src/retail_voice.c/.h` | Mensaje de voz: grabar (mantener), escuchar, repetir y compartir |
| `src/retail_voice_mac.m` | macOS: permiso de micrófono, conversión a M4A, portapapeles y apertura de WhatsApp |
| `src/retail_number_font.c` | Fuente de los números (generada desde Montserrat Bold, OFL) |
| `src/mosceye_logo.c` | Emblema MOSCEYE en formato LVGL (generado, no editar) |
| `src/main.c` | `main` del simulador del SDK con el cableado MOSCEYE (flag `--retail`, cola de eventos de puntero, verbos de escenario) |
| `CMakeLists.txt` | CMake del simulador del SDK con las fuentes MOSCEYE, SDL con audio y frameworks de macOS |
| `Info.plist` | Info.plist embebido en el binario del simulador (micrófono) |

## Cómo se usa

Estos archivos viven normalmente dentro de una copia de
[muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk):

```sh
# dentro del SDK, en esp32/simulator/
cp -R <este-repo>/simulador/src/*.c <este-repo>/simulador/src/*.h \
      <este-repo>/simulador/src/*.m esp32/simulator/src/
cp <este-repo>/simulador/CMakeLists.txt <este-repo>/simulador/Info.plist esp32/simulator/
cmake -S esp32/simulator -B esp32/simulator/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build esp32/simulator/build --parallel
./esp32/simulator/build/muse_simulator --retail
```

La forma normal de arrancar todo (servidor + Desktop + Charm) es desde la raíz
del repo MOSCEYE:

```sh
./run_demo.sh
```

## Contrato con el servidor

Sin red entre Charm y el motor: todo pasa por archivos locales escritos de
forma atómica.

| Archivo | Dirección | Contenido |
|---|---|---|
| `/tmp/mosceye_trigger.json` | Charm → servidor | `{"action":"check"}` al pulsar CHEQUEAR; `{"action":"start"}` al pulsar EMPEZAR |
| `/tmp/mosceye_trigger_ack.json` | servidor → Charm | Confirmación del chequeo con IDs de request |
| `/tmp/caja_status.json` | servidor → Charm | Resultado v2: conteos, fase, error, antigüedad y heartbeat |

EMPEZAR reinicia la demo: el servidor vuelve a reproducir el video desde el
principio y descarta el análisis anterior en todas las pantallas.

## Detalles de implementación que conviene saber

- Los eventos de puntero se **encolan** en el event watch de SDL y se aplican
  en el bucle principal antes de `lv_timer_handler()`. Aplicarlos dentro del
  procesamiento de entrada de LVGL provocó un segfault al arrastrar fuera de
  la ventana (ver `CHANGELOG.md`, v0.2.2).
- Los verbos de escenario (`tap`, `swipe`, y `drag=X1,Y1,X2,Y2,STEPS`) existen
  para los tests headless de navegación en `tests/test_charm_navigation.py`.
- Las etiquetas dicen "CAJA ATENDIDA / CAJA SIN ATENDER" y "PERSONAS
  VISIBLES": son estimaciones posicionales por zonas, no identidad.

## Licencias

Código bajo Apache License 2.0 (Meta Platforms). Los glifos de
`retail_number_font.c` derivan de Montserrat Bold (SIL Open Font License 1.1;
ver `assets/Montserrat-OFL.txt` en la raíz del repo). El emblema MOSCEYE es un
asset generado a partir del logo del proyecto.
