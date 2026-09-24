# Grabador OpenArgentOS

Grabador y capturador de pantalla para **OpenArgentOS**.

Aplicación de escritorio escrita en **Python** con **GTK 4** y **libadwaita**, usando **ffmpeg** (`x11grab`) para capturar y grabar en sesiones X11 / XWayland.

[![GTK](https://img.shields.io/badge/GTK-4-green)](https://www.gtk.org/)
[![libadwaita](https://img.shields.io/badge/libadwaita-1-blue)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

---

## Características

- Captura de pantalla completa (PNG)
- Grabación de pantalla a **MP4 / MKV (H.264)** o **WEBM (VP9)**
- **30 FPS** por defecto (60 FPS opcional, más demanda de CPU)
- Cuenta regresiva configurable antes de **grabar** y antes de **capturar**
- Selector de tema: **Sistema / Claro / Oscuro**
- Icono en la **bandeja del sistema** (StatusNotifierItem; Ayatana si está disponible)
- Menú de controles al hacer clic en el icono de bandeja
- Integración **MPRIS2** (controles multimedia del panel mientras se graba)
- Guarda en las carpetas XDG del usuario (`Videos`, `Pictures`)
- Interfaz no bloqueante al iniciar o detener ffmpeg
- Detección de sesión X11 / Wayland

---

## Instalación

### 1. Dependencias del sistema

Instalá primero las dependencias de runtime (Debian / Ubuntu / OpenArgentOS):

```bash
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg
```

**Opcional** — mejor soporte de bandeja en Cinnamon, Ubuntu y derivados:

```bash
sudo apt install libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1
```

En **Cinnamon**, asegurate de tener el applet **System Tray** (o **Systray**) activo en el panel  
*(clic derecho en el panel → Applets)*.

### 2. Elegí un método de instalación

#### Opción A — Paquete `.deb` (recomendado)

1. Descargá el archivo `grabador-openargentos_1.1.0_all.deb` desde la sección
   [Releases](https://github.com/OpenArgentOS/grabador-openargentos/releases) del repositorio.
2. Instalalo:

```bash
sudo apt install ./grabador-openargentos_1.1.0_all.deb
```

Si `apt` no resuelve las dependencias automáticamente:

```bash
sudo dpkg -i grabador-openargentos_1.1.0_all.deb
sudo apt-get install -f
```

3. Ejecutalo desde el menú de aplicaciones o desde la terminal:

```bash
grabador-openargentos
```

#### Opción B — AppImage

1. Descargá `Grabador_OpenArgentOS-1.1.0-x86_64.AppImage` desde
   [Releases](https://github.com/OpenArgentOS/grabador-openargentos/releases).
2. Dale permisos de ejecución y arrancalo:

```bash
chmod +x Grabador_OpenArgentOS-1.1.0-x86_64.AppImage
./Grabador_OpenArgentOS-1.1.0-x86_64.AppImage
```

> El AppImage usa el **Python del sistema** (y GTK 4 / libadwaita / ffmpeg del host).  
> No empaqueta el runtime gráfico completo: las dependencias del paso 1 deben estar instaladas.

#### Opción C — Desde el código fuente

```bash
git clone https://github.com/OpenArgentOS/grabador-openargentos.git
cd grabador-openargentos
python3 grabador_openargentos.py
```

No requiere instalación: alcanza con las dependencias del sistema y el archivo `.py`.

### 3. Desinstalación

**Paquete `.deb`:**

```bash
sudo apt remove grabador-openargentos
```

**AppImage:** borrá el archivo `.AppImage`.

**Código fuente:** no instala archivos en el sistema; solo eliminá la carpeta del repo.

---

## Uso rápido

```bash
python3 grabador_openargentos.py
# o, si instalaste el .deb:
grabador-openargentos
```

1. Elegí formato (MP4 / MKV / WEBM) y FPS.
2. Configurá la cuenta regresiva de grabación o de captura.
3. Pulsá **Iniciar Grabación** o **Capturar**.
4. Los archivos se guardan en `~/Videos` y `~/Pictures` (o las rutas XDG del usuario).

### Controles de bandeja

- **Clic en el icono**: menú con iniciar/detener, captura, mostrar/ocultar ventana y salir.
- **Mientras grabás**: el applet de sonido/medios del panel puede mostrar el reproductor MPRIS *Grabador OpenArgentOS* (Play / Pause / Stop).

---

## Requisitos

| Componente | Paquete típico (Debian/Ubuntu) |
|------------|--------------------------------|
| Python 3.10+ | `python3` |
| PyGObject | `python3-gi` |
| GTK 4 | `gir1.2-gtk-4.0` |
| libadwaita | `gir1.2-adw-1` |
| ffmpeg | `ffmpeg` |

### Sesión gráfica

- Compatible: **X11** y **XWayland**
- En **Wayland nativo** la captura y la grabación quedan deshabilitadas (limitación de `x11grab`). Soporte vía portal + PipeWire está en el roadmap.

---

## Construir paquetes

### `.deb`

```bash
chmod +x scripts/build-deb.sh
./scripts/build-deb.sh
```

Salida: `dist/grabador-openargentos_1.1.0_all.deb`

### AppImage

```bash
chmod +x scripts/build-appimage.sh
./scripts/build-appimage.sh
```

Salida: `dist/Grabador_OpenArgentOS-1.1.0-<arch>.AppImage`

En entornos sin FUSE, el script también genera un tarball del AppDir.

---

## Estructura del proyecto

```text
grabador_openargentos.py    # Aplicación principal
README.md
scripts/
  build-deb.sh              # Genera el paquete Debian
  build-appimage.sh         # Genera el AppImage / AppDir
packaging/
  deb/                      # Árbol del paquete .deb
  appimage/                 # AppDir temporal de build
dist/                       # Artefactos generados
```

---

## Limitaciones

- Solo **X11** / **XWayland** para captura y grabación (`x11grab`).
- En **Wayland nativo** los botones de captura/grabación se deshabilitan hasta integrar `xdg-desktop-portal` + PipeWire.
- VP9 en tiempo real consume más CPU que H.264; se recomienda **MP4** o **MKV**.
- La bandeja depende del soporte del escritorio (Cinnamon, KDE, XFCE, etc.).

---

## Roadmap

- [ ] Captura y grabación en Wayland (portal + PipeWire)
- [ ] Selección de región o ventana
- [ ] Audio del sistema y/o micrófono
- [ ] Preferencias persistentes (GSettings)
- [ ] Atajos de teclado globales

---

## Licencia

MIT — proyecto **OpenArgentOS**.

## Créditos

- [ffmpeg](https://ffmpeg.org/)
- [GTK](https://www.gtk.org/) / [libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/)
- Specs [StatusNotifierItem](https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem/) y [MPRIS2](https://specifications.freedesktop.org/mpris-spec/latest/)
