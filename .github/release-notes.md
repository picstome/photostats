## Español

### Novedades de la 1.1.0

- **La caché puede vivir en otro disco.** Deja las fotos en el disco lento y
  pon los estadísticos en el SSD: **Ajustes → Copia de las estadísticas**. En
  una biblioteca de 539.000 fotos, una pantalla completa de estadísticas pasa de
  minutos a alrededor de un segundo.
- **Mover la caché sin reescanear.** El botón *Mover la base de datos a otra
  carpeta…* copia la caché existente, ya compactada, a la carpeta que elijas. No
  vuelve a leer ni una foto.
- **Una caché por biblioteca**, para que varias bibliotecas puedan compartir la
  misma carpeta sin pisarse. Si ya tenías una caché en la carpeta elegida, se
  adopta tal cual, sin reindexar.
- **Formato interno más rápido (v4).** Los metadatos en bruto salen de la tabla
  que se consulta en cada pantalla: la base de datos se migra sola al abrirla,
  sin reescanear, ocupa alrededor de un 7 % menos y las consultas van sobre un
  30 % más rápidas.
- **Aviso si una caché pertenece a otra biblioteca**, en vez de podarla sin
  decir nada.
- La línea de comandos respeta la ubicación de la caché.

### Descargas por plataforma

| Plataforma | Archivo |
|---|---|
| **macOS** (Apple Silicon, Procesadores M) | `Photo Stats-arm64.dmg` |
| **macOS** (Intel) | `Photo Stats-x64.dmg` |
| **Windows** | `PhotoStats-windows.zip` (o `PhotoStats-Setup.exe`) |
| **Linux** | `PhotoStats-linux.tar.gz` |

### ⚠️ Permisos en macOS (Desarrollador no identificado)

Si macOS bloquea la app por no estar firmada:

1. Ve a **Ajustes del Sistema** > **Privacidad y seguridad**.
2. Baja hasta **Seguridad** y verás el aviso *"Se bloqueó Photo Stats…"*.
3. Pulsa el botón **Abrir de todos modos** (*Open Anyway*) e introduce tu contraseña.

*(También puedes hacer clic derecho sobre la app instalada > **Abrir** > **Abrir**).*

### Requisito previo: exiftool

Photo Stats necesita `exiftool` en el sistema para leer los metadatos:

* **macOS:** `brew install exiftool`
* **Windows:** Descarga `exiftool.exe` de [exiftool.org](https://exiftool.org) y ponlo en tu PATH (o selecciónalo en **Ajustes** dentro de la app).
* **Linux:** `sudo apt install libimage-exiftool-perl`

---

## English

### What's new in 1.1.0

- **The cache can live on another disk.** Keep the photos on the slow drive and
  put the statistics on the SSD: **Settings → Statistics cache**. On a
  539,000-photo library a full screen of statistics went from minutes to about a
  second.
- **Move the cache without a rescan.** *Move the cache to another folder…*
  copies the existing cache, already compacted, to the folder you choose. It
  does not read a single photo again.
- **One cache per library**, so several libraries can share one cache folder
  without trampling each other. A cache already sitting in the chosen folder is
  adopted as is, with no reindexing.
- **Faster internal format (v4).** The raw metadata moves out of the table every
  screen scans: the database migrates itself on open, without a rescan, is about
  7% smaller and the queries run about 30% faster.
- **A warning when a cache belongs to another library**, instead of silently
  pruning it.
- The command line respects the cache location.

### Downloads by Platform

| Platform | File |
|---|---|
| **macOS** (Apple Silicon, M processor) | `Photo Stats-arm64.dmg` |
| **macOS** (Intel) | `Photo Stats-x64.dmg` |
| **Windows** | `PhotoStats-windows.zip` (or `PhotoStats-Setup.exe`) |
| **Linux** | `PhotoStats-linux.tar.gz` |

### ⚠️ macOS Permissions (Unidentified Developer)

If macOS blocks the app on first launch:

1. Open **System Settings** > **Privacy & Security**.
2. Scroll down to **Security** to find *"Photo Stats was blocked…"*.
3. Click **Open Anyway** and confirm with your password.

*(Alternatively, right-click the app > **Open** > **Open**).*

### Prerequisite: exiftool

Photo Stats requires `exiftool` to read EXIF metadata:

* **macOS:** `brew install exiftool`
* **Windows:** Download `exiftool.exe` from [exiftool.org](https://exiftool.org) and place it in your PATH (or locate it via **Settings** in the app).
* **Linux:** `sudo apt install libimage-exiftool-perl`
