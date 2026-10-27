# Versionado de MOSCEYE

MOSCEYE vive en **dos repositorios locales**, porque la raíz del workspace no es
un repositorio y no conviene anidar uno dentro del otro:

| Ruta | Repositorio | Qué cubre |
|---|---|---|
| `mosceye/` | git propio (`mosceye/.git`) | Motor Python, Desktop, tests, auditorías, script de arranque |
| `muse-gadget-sdk/` | repo existente (rama `main`) | Simulador, UI Charm, voz, skill `retail-tracker` |

## Verificar

```sh
git -C mosceye status --short
git -C muse-gadget-sdk status --short
git -C mosceye log --oneline -3
git -C muse-gadget-sdk log --oneline -3
```

## Etiquetas

- `mosceye` → `v0.2.0` (estado previo a las mejoras de la auditoría).
- `muse-gadget-sdk` → `mosceye-v0.2.0` (UI/voz/skill preservados).

## Qué no se versiona

Por tamaño o privacidad, `.gitignore` excluye:

- `mosceye/.venv/` (~944 MB)
- `mosceye/checkpoints/` (~358 MB)
- `mosceye/backups/`
- `mosceye/MOSCEYE Charm.app/` (bundle generado)
- `mosceye/audit/evidence/**/*.jpg|png|mp4` (pueden contener rostros)

Los pesos y el video se respaldan fuera de git. El respaldo de código previo a
estas mejoras está en el directorio temporal aprobado:

```
/private/var/folders/gr/zhhnkhvj60sbgmmvk79w8mkh0000gn/T/opencode/mosceye-backup/code-2026-10-26-pre-mejoras.tgz
```

## Regla práctica

Antes de un cambio grande:

```sh
git -C mosceye add -A && git -C mosceye commit -m "checkpoint: ..."
git -C muse-gadget-sdk add -A && git -C muse-gadget-sdk commit -m "checkpoint: ..."
```

Nunca uses `git clean -fdx` en `muse-gadget-sdk`: aunque los archivos de MOSCEYE
ya están commiteados, borraría builds y artefactos locales.
